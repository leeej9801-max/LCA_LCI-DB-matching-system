"""BOM 매칭: 행의 norm_text 로 후보를 찾아 match_run·match_candidate 에 저장하고, 세션 읽기(A02)에 쓸 Row 를 만든다.

검색은 app.search 의 함수를 그대로 호출한다. 같은 query_key 는 한 번만 검색해 결과를 공유한다(spec/08 §4).
사전·Veto·재순위·환산은 아직 없다.
"""
import secrets
from collections import OrderedDict
from datetime import datetime

from app.bom.convert import convert
from app.embedder import BATCH, DIM
from app.roles import LABEL
from app.search import RRF_K, TOP, dense_rank, load_index, rrf, tfidf_rank

TOP_N = 20  # 저장하는 후보 수(설정값)
AMBIGUOUS_RULE = "TF-IDF 목록의 1위와 밀집 목록의 1위가 서로 다른 name_ko 이면 true. 같은 이름이거나 한쪽 목록에 후보가 없으면 false (임계값 없음)"
# 구분(BOM 입력)별 검색 범위: 데이터셋 역할 코드. 구분이 없으면 전체(제한 없음). 필터는 순위를 자르기 전에 건다
ROLE_FILTER = {"material": ["material", "combined"], "process": ["process"]}
ROLE_FILTER_RULE = ("구분 소재 → 데이터셋 역할 {소재, 합본}에서만, 구분 공정 → {공정}에서만, 구분 없음 → 전체. "
                    "TF-IDF 는 전체 인덱스로 학습(IDF 유지)하고 허용 역할만 순위를 매기며, 밀집은 SQL 에서 역할 조건을 건다")
CACHE_SIZE = 2048  # 질의 임베딩 LRU 캐시 크기(설정값)
# 신뢰도는 순위 기반의 임시 규칙이다. 점수(RRF)는 확률이 아니므로 보정 전까지 이렇게만 한다.
CONFIDENCE_RULE = "높음: TF-IDF·밀집 두 목록 모두 1위 / 보통: 두 목록 모두 3위 안, 또는 한쪽에서 1위 / 낮음: 그 밖 (순위 기반 임시 규칙, 보정 전)"


class EmbedCache:
    """텍스트 → 벡터 LRU(프로세스 메모리)."""

    def __init__(self, size=CACHE_SIZE):
        self.size, self.data = size, OrderedDict()

    def get(self, text):
        if text in self.data:
            self.data.move_to_end(text)
            return self.data[text]
        return None

    def put(self, text, vector):
        self.data[text] = vector
        self.data.move_to_end(text)
        while len(self.data) > self.size:
            self.data.popitem(last=False)


CACHE = EmbedCache()


def embed_queries(embedder, texts, cache=CACHE):
    """({텍스트: 벡터}, 캐시 적중 수). 캐시에 없는 것만 배치(32)로 임베딩."""
    vectors, missing, hits = {}, [], 0
    for t in texts:
        v = cache.get(t)
        if v is None:
            missing.append(t)
        else:
            vectors[t], hits = v, hits + 1
    for i in range(0, len(missing), BATCH):
        chunk = missing[i:i + BATCH]
        for t, v in zip(chunk, embedder.embed(chunk)):
            cache.put(t, v)
            vectors[t] = v
    return vectors, hits


def confidence(rank_tfidf, rank_dense):
    """순위 기반 임시 규칙(CONFIDENCE_RULE)."""
    if rank_tfidf == 1 and rank_dense == 1:
        return "높음"
    if (rank_tfidf is not None and rank_tfidf <= 3 and rank_dense is not None and rank_dense <= 3) or 1 in (rank_tfidf, rank_dense):
        return "보통"
    return "낮음"


def score01(score_rrf, k=RRF_K):
    """Candidate.score: rrf 를 두 목록 모두 1위일 때의 값(2/(k+1))으로 나눠 0~1 로 자른 상대값. 확률이 아니며 근거로 쓰지 않는다."""
    return max(0.0, min(1.0, score_rrf / (2 / (k + 1))))


def match_project(conn, project_id, embedder, progress=lambda done, total: None, digest=(None, None)):
    """세션의 행을 검색해 match_run 하나를 만든다. 반환: {run_id, queries, cache_hits}. conn 의 트랜잭션 안에서 쓴다."""
    items = conn.execute("SELECT query_key, norm_text, input_role FROM bom_item WHERE project_id = %s AND norm_text <> '' ORDER BY row_no",
                         (project_id,)).fetchall()
    queries = {key: (text, role) for key, text, role in items}  # 같은 query_key 는 한 번만
    progress(0, len(queries))  # 임베딩이 오래 걸려도 "후보 검색"의 total 이 처음부터 보인다(T9b.2)
    version_id, model_name, idx_items = load_index(conn)  # 작업 시작 때 한 번
    if embedder.model_name != model_name:
        raise RuntimeError(f"인덱스 {version_id}의 모델은 {model_name}인데 임베더는 {embedder.model_name}입니다")
    sn = {it["dataset_id"]: it["list_sn"] for it in idx_items}
    vectors, hits = embed_queries(embedder, list({text for text, _ in queries.values()}))
    role_of = dict(conn.execute("SELECT dataset_id, role FROM lci_dataset").fetchall())
    allowed_ids = {role: {d for d, r in role_of.items() if r in codes} for role, codes in ROLE_FILTER.items()}

    run_id = f"run-{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(3)}"
    config = {"top_n": TOP_N, "rrf_k": RRF_K, "search_top": TOP, "ambiguous_rule": AMBIGUOUS_RULE, "confidence_rule": CONFIDENCE_RULE,
              "query": "norm_text(사전 없음)", "role_filter_rule": ROLE_FILTER_RULE}
    model_versions = {"index_version_id": version_id, "embed_model": model_name, "ollama_digest": digest[0],
                      "ollama_digest_error": digest[1], "dim": DIM}
    conn.execute("INSERT INTO match_run (run_id, project_id, config, model_versions) VALUES (%s, %s, %s, %s)",
                 (run_id, project_id, _json(config), _json(model_versions)))
    rows = []
    for done, (key, (text, role)) in enumerate(queries.items(), start=1):
        t = tfidf_rank(idx_items, text, TOP, allowed_ids.get(role))
        d = dense_rank(conn, version_id, model_name, vectors[text], TOP, ROLE_FILTER.get(role))
        t_pos = {ds: (r, s) for r, (ds, s) in enumerate(t, 1)}
        d_pos = {ds: (r, s) for r, (ds, s) in enumerate(d, 1)}
        for rank, (ds, s) in enumerate(rrf([t, d], sn)[:TOP_N], start=1):
            rt, st = t_pos.get(ds, (None, None))
            rd, sd = d_pos.get(ds, (None, None))
            rows.append((run_id, key, rank, ds, rt, rd, st, sd, s, confidence(rt, rd)))
        progress(done, len(queries))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO match_candidate (run_id, query_key, rank, dataset_id, rank_tfidf, rank_dense, score_tfidf, score_dense, "
                        "score_rrf, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    conn.execute("UPDATE match_run SET finished_at = now() WHERE run_id = %s", (run_id,))
    return {"run_id": run_id, "queries": len(queries), "cache_hits": hits}


def _json(v):
    from psycopg.types.json import Jsonb
    return Jsonb(v)


# ---------- 세션 읽기(A02) ----------
def version_or_none(v):
    return None if v == "-" else v  # 목록의 '-' 는 버전 없음 자리표시(T8.1)


ITEM_COLS = ["row_no", "source_row", "input_role", "part_no", "raw_name", "raw_spec", "raw_unit", "raw_qty", "clean_name", "clean_spec", "clean_unit",
             "clean_unit_display", "clean_qty", "norm_text", "query_key", "issues", "target_status", "target_reason", "selected_id",
             "selected_manual", "override_thickness_mm", "override_density_kg_m3", "override_unit_mass_kg", "review_status", "review_note",
             "explanation"]
DATASET_COLS = ["dataset_id", "name_ko", "category", "ref_flow_unit", "ref_flow_amount", "role"]


def build_rows(conn, project_id, row_no=None):
    """SessionPayload.rows(row_no 를 주면 그 행 하나만). conn 은 튜플 행을 돌려주는 접속."""
    items = [dict(zip(ITEM_COLS, r)) for r in conn.execute(
        f"SELECT {', '.join(ITEM_COLS)} FROM bom_item WHERE project_id = %s AND (%s::int IS NULL OR row_no = %s) ORDER BY row_no",
        (project_id, row_no, row_no)).fetchall()]
    run = conn.execute("SELECT run_id FROM match_run WHERE project_id = %s ORDER BY started_at DESC LIMIT 1", (project_id,)).fetchone()
    keys = list({it["query_key"] for it in items})
    cands = {}
    if run and keys:
        for r in conn.execute(
                "SELECT c.query_key, c.rank, c.dataset_id, c.rank_tfidf, c.rank_dense, c.score_rrf, c.vetoed, c.veto_rule_id, c.confidence, "
                "d.name_ko, d.name_en, d.category, d.developer, d.dev_year, d.version, d.ref_flow_unit, d.has_xml, d.geography, d.allocation, "
                "d.cutoff, d.tech_description, d.list_sn, d.role FROM match_candidate c JOIN lci_dataset d USING (dataset_id) "
                "WHERE c.run_id = %s AND c.query_key = ANY(%s) ORDER BY c.query_key, c.rank", (run[0], keys)).fetchall():
            cands.setdefault(r[0], []).append(dict(zip(
                ["query_key", "rank", "dataset_id", "rank_tfidf", "rank_dense", "score_rrf", "vetoed", "veto_rule_id", "confidence", "name_ko",
                 "name_en", "category", "org", "year", "version", "reference_unit", "has_xml", "geography", "allocation", "cutoff", "tech",
                 "list_sn", "role"], r)))
    names = {c["name_ko"] for cs in cands.values() for c in cs}
    groups = {}  # name_ko → [(dataset_id, year, list_sn)] lci_dataset 전체
    if names:
        for name, ds, year, sn_ in conn.execute(
                "SELECT name_ko, dataset_id, dev_year, list_sn FROM lci_dataset WHERE name_ko = ANY(%s)", (list(names),)).fetchall():
            groups.setdefault(name, []).append((ds, year, sn_))
    # 선택된 데이터셋(후보 밖 직접 선택 포함)과 기본 선택(1순위)의 기준 단위·기준량
    wanted = {it["selected_id"] for it in items if it["selected_id"]} | {c["dataset_id"] for cs in cands.values() for c in cs}
    datasets = {}
    if wanted:
        datasets = {r[0]: dict(zip(DATASET_COLS, r)) for r in conn.execute(
            f"SELECT {', '.join(DATASET_COLS)} FROM lci_dataset WHERE dataset_id = ANY(%s)", (list(wanted),)).fetchall()}
    return [row_payload(it, cands.get(it["query_key"], []), groups, datasets) for it in items]


def newest(members):
    return max(members, key=lambda m: (m[1] is not None, m[1] or 0, m[2]))


def fold(cands, groups, n=3):
    """저장된 후보(순위순)를 동명 묶음으로 접어 앞에서 n개. 대표 = 그 이름의 저장 후보 중 최신 연도(같으면 list_sn 큰 것)."""
    by_name, order = {}, []
    for c in cands:
        if c["name_ko"] not in by_name:
            order.append(c["name_ko"])
        by_name.setdefault(c["name_ko"], []).append(c)
    out = []
    for name in order[:n]:
        members = by_name[name]
        out.append(max(members, key=lambda c: (c["year"] is not None, c["year"] or 0, c["list_sn"])))
    return out


def reasons_for(c, query, groups, input_role=None):
    """사실만 적는다(사전·Veto 근거는 아직 없음)."""
    rt, rd = c["rank_tfidf"], c["rank_dense"]
    out = [f"TF-IDF {f'{rt}위' if rt else '상위 100 밖'} · 밀집 {f'{rd}위' if rd else '상위 100 밖'}"]
    group = groups.get(c["name_ko"], [])
    if len(group) > 1:
        latest = newest(group)[0] == c["dataset_id"]
        out.append(f"이름이 같은 데이터셋 {len(group)}건 중 {'최신' if latest else '하나'}")
    name, q = c["name_ko"].replace(" ", "").lower(), query.replace(" ", "").lower()
    if name and q and (name in q or q in name):
        out.append("질의와 이름 부분 일치")
    if input_role in ROLE_FILTER:  # 필터가 걸린 행
        label = LABEL[input_role]
        out.append(f"구분 '{label}' → {label} 데이터셋 안에서 찾음")
    if c["role"] == "combined":
        out.append("소재와 공정이 합쳐진 데이터셋 — 같은 부품의 공정 행과 겹치지 않는지 확인")
    return out


def candidate_payload(c, query, groups, input_role=None):
    group = groups.get(c["name_ko"], [])
    others = [ds for ds, _, _ in sorted(group, key=lambda m: (m[1] is not None, m[1] or 0, m[2]), reverse=True) if ds != c["dataset_id"]]
    return {
        "dataset_id": c["dataset_id"], "name": c["name_ko"], "name_en": c["name_en"], "category": c["category"], "org": c["org"],
        "year": c["year"], "version": version_or_none(c["version"]), "reference_unit": c["reference_unit"], "score": score01(c["score_rrf"]),
        "confidence": c["confidence"], "reasons": reasons_for(c, query, groups, input_role),
        "veto": {"rule_id": c["veto_rule_id"], "reason": ""} if c["vetoed"] else None,
        "duplicate_group": {"size": len(group), "others": others} if len(group) > 1 else None,
        "role": LABEL.get(c["role"]), "has_xml": c["has_xml"], "geography": c["geography"], "allocation": c["allocation"], "cutoff": c["cutoff"], "tech_summary": c["tech"],
    }


def is_ambiguous(cands):
    """검색 두 방식의 1위가 서로 다른 이름이면 true(AMBIGUOUS_RULE). 한쪽 목록에 후보가 없으면(저장된 후보에 1위가 없으면) false."""
    first_tfidf = next((c["name_ko"] for c in cands if c["rank_tfidf"] == 1), None)
    first_dense = next((c["name_ko"] for c in cands if c["rank_dense"] == 1), None)
    return first_tfidf is not None and first_dense is not None and first_tfidf != first_dense


def num(v):
    return None if v is None else float(v)  # numeric(Decimal) → float


def row_payload(it, cands, groups, datasets=None):
    """Row(스펙 07). it 은 ITEM_COLS 의 dict. selected_manual 이 NULL 이면 아직 사람이 선택을 건드리지 않은 행 → 1순위가 기본 선택."""
    datasets = datasets or {}
    shown = [candidate_payload(c, it["norm_text"], groups, it.get("input_role")) for c in fold(cands, groups)]
    overrides = {k: num(it.get(f"override_{k}")) for k in ("thickness_mm", "density_kg_m3", "unit_mass_kg")}
    overrides = {k: v for k, v in overrides.items() if v is not None}
    touched = it.get("selected_manual") is not None
    selected_id = it.get("selected_id") if touched else (shown[0]["dataset_id"] if shown else None)
    selected = conversion = None
    if selected_id:
        cand = next((c for c in shown if c["dataset_id"] == selected_id), None)
        ds = datasets.get(selected_id) or {}
        if cand:  # 후보(Top-3) 안: 그 후보의 점수·신뢰도. 차단 후보를 고른 경우만 manual
            selected = {k: cand[k] for k in ("dataset_id", "name", "category", "reference_unit", "score", "confidence", "role")} | {
                "manual": cand["veto"] is not None}
        else:  # 후보 밖(직접 선택): 점수가 없다
            selected = {"dataset_id": selected_id, "name": ds.get("name_ko"), "category": ds.get("category"),
                        "reference_unit": ds.get("ref_flow_unit"), "score": None, "confidence": None, "manual": True,
                        "role": LABEL.get(ds.get("role"))}
        conversion = convert(it["clean_qty"], it["clean_unit"], it["clean_unit_display"], ds.get("ref_flow_unit"),
                             num(ds.get("ref_flow_amount")), overrides)
    return {
        "id": it["row_no"], "source_row": it["source_row"], "input_role": LABEL.get(it.get("input_role")), "part_no": it.get("part_no"),
        "raw": {"name": it["raw_name"], "spec": it["raw_spec"], "unit": it["raw_unit"], "quantity": it["raw_qty"]},
        "clean": {"name": it["clean_name"], "spec": it["clean_spec"], "unit": it["clean_unit"], "unit_display": it["clean_unit_display"],
                  "quantity": it["clean_qty"]},
        "normalized_name": it["norm_text"], "synonym_hits": [], "attrs": {}, "issues": it["issues"],
        "target": {"status": it["target_status"], "reason": it["target_reason"]},
        "match_state": "candidate" if shown else "no_answer",  # 점수 기준 정답 없음 판정은 하지 않는다(보정 전)
        "candidates": shown, "ambiguous": is_ambiguous(cands),
        "selected_id": selected_id, "selected": selected,
        "overrides": overrides,
        "review": {"status": it.get("review_status") or ("excluded" if it["target_status"] == "제외" else "pending"),
                   "note": it.get("review_note") or ""},
        "conversion": conversion, "explanation": it.get("explanation"),
    }


def summarize(rows):
    """Summary. 스펙에 정의가 없는 필드는 프론트 mock(sessions.js)의 계산 규칙을 따른다."""
    def n(f):
        return sum(1 for r in rows if f(r))
    return {
        "total": len(rows), "target": n(lambda r: r["target"]["status"] == "대상"), "exclude": n(lambda r: r["target"]["status"] == "제외"),
        "needs_review": n(lambda r: r["review"]["status"] == "pending"), "with_issues": n(lambda r: len(r["issues"]) > 0),
        "needs_info": n(lambda r: (r["conversion"] or {}).get("status") == "needs_info"),
        "high_confidence": n(lambda r: bool(r["candidates"]) and r["candidates"][0]["confidence"] == "높음"),
        "review": {k: n(lambda r, k=k: r["review"]["status"] == k) for k in ("pending", "approved", "rejected", "excluded")},
        "match": {k: n(lambda r, k=k: r["match_state"] == k) for k in ("candidate", "vetoed", "no_answer")},
    }
