"""BOM 매칭: 행의 norm_text 로 후보를 찾아 match_run·match_candidate 에 저장하고, 세션 읽기(A02)에 쓸 Row 를 만든다.

검색은 app.search 의 함수를 그대로 호출한다. 같은 query_key 는 한 번만 검색해 결과를 공유한다(spec/08 §4).
재순위·LLM 판정은 없다. 사전(D)·Veto 강등(Vd)·신뢰도 규칙(R1)은 평가와 같은 함수를 쓴다(E4a, 설정은 아래 상수 한 곳).
"""
import secrets
from collections import OrderedDict
from datetime import datetime

from app.bom.convert import convert
from app.bom.infer_role import infer_role
from app.bom.lexicon import NON_DEV, expand, origin_counts, synonyms_sha256
from app.bom.veto import VETO_EXCLUDE, demote, demoted_note, effective_role, veto_filters
from app.carbon import carbon_of
from app.embedder import BATCH, DIM
from app.roles import LABEL
from app.search import RRF_K, TOP, dense_rank, load_index, rrf, tfidf_rank

TOP_N = 100  # 저장하는 후보 수(설정값). 평가의 검색 깊이(TOP)와 같게 둔다: 앱이 보여 줄 때 하는 동명 접기(대표 = 최신 판)가 평가(C1+G)와 같아진다(E4d)
AMBIGUOUS_RULE = "TF-IDF 목록의 1위와 밀집 목록의 1위가 서로 다른 name_ko 이면 true. 같은 이름이거나 한쪽 목록에 후보가 없으면 false (임계값 없음)"
# 구분(BOM 입력)별 검색 범위: 데이터셋 역할 코드. 구분이 없으면 전체(제한 없음). 필터는 순위를 자르기 전에 건다
ROLE_FILTER = {"material": ["material", "combined"], "process": ["process"]}
ROLE_FILTER_RULE = ("사용자가 구분을 직접 적은 행만 필터: 구분 소재 → 데이터셋 역할 {소재, 합본}에서만, 구분 공정 → {공정}에서만. "
                    "TF-IDF 는 전체 인덱스로 학습(IDF 유지)하고 허용 역할만 순위를 매기며, 밀집은 SQL 에서 역할 조건을 건다. "
                    "구분이 비어 있으면 필터하지 않고, 품명에서 추정한 소재/공정의 반대 역할 후보를 뒤로 보낸다(Veto 강등 Vd, app/bom/veto.py)")
CACHE_SIZE = 2048  # 질의 임베딩 LRU 캐시 크기(설정값)
# 신뢰도는 순위 기반의 임시 규칙이다. 점수(RRF)는 확률이 아니므로 보정 전까지 이렇게만 한다.
CONFIDENCE_RULE = ("높음: TF-IDF·밀집 두 목록 모두 1위 / 보통: 두 목록 모두 3위 안, 또는 한쪽에서 1위(다른 쪽도 상위 100위 안일 때만) / "
                   "낮음: 그 밖, 한쪽 목록에 아예 없으면 최대 낮음 (순위 기반 임시 규칙, 보정 전)")
# "맞는 후보 없음": 대표 1순위 후보(동명 접은 뒤 첫 후보)의 신뢰도가 이 값이면 no_answer. 후보가 없어도 no_answer. 후보 목록은 참고용으로 남긴다
NO_ANSWER_CONFIDENCE = "낮음"
# --- 검색 설정(E4a). 값을 바꾸면 match_run.config 에 그대로 기록된다. 평가의 케이스 표기와 대응: rrf/dense = C2/C1, D/Ds = 사전, Vd/V = Veto ---
SEARCH_BASE = "dense"               # "rrf"(TF-IDF+밀집 RRF) | "dense"(밀집만; TF-IDF 순위·점수는 근거와 신뢰도 판정용으로 계속 저장)
LEXICON_MODE = "D"                  # None | "D"(사전 전체) | "Ds"(출처 dev 항목 제외)
VETO_MODE = "Vd"                    # None | "V"(제외) | "Vd"(반대 역할을 뒤로, 지우지 않음)
CONFIDENCE = ("R1", {"tau": 0.55})  # ("R0", {}) 현재 규칙 | ("R1", {"tau": τ}) R0 + '높음'은 밀집 점수 ≥ τ 일 때만
CONFIDENCE_RULE_R1 = "R1: 위 '높음'이어도 밀집 점수가 {tau} 미만이면 '보통'으로 내림 (평가 app.evaluation.confidence_rules 와 같은 함수)"
NO_ANSWER_RULE = "대표 1순위 후보(동명 접은 뒤 첫 후보)의 신뢰도가 '낮음'이거나 후보가 없으면 no_answer. 후보 목록은 지우지 않는다(참고용)"


def current_settings():
    """위 상수를 지금 값으로 읽는다(모듈 값을 바꾸거나 시험에서 monkeypatch 해도 반영)."""
    return {"search_base": SEARCH_BASE, "lexicon_mode": LEXICON_MODE, "veto_mode": VETO_MODE,
            "confidence": {"rule": CONFIDENCE[0], "params": dict(CONFIDENCE[1])}}


def check_settings(cfg):
    """알 수 없는 조합이면 ValueError. 앱은 R2·R3 를 쓰지 않는다(밀집 1·2위 점수 차를 저장하지 않음)."""
    if cfg["search_base"] not in ("rrf", "dense"):
        raise ValueError(f"SEARCH_BASE 는 rrf 또는 dense: {cfg['search_base']!r}")
    if cfg["lexicon_mode"] not in (None, "D", "Ds"):
        raise ValueError(f"LEXICON_MODE 는 None·D·Ds: {cfg['lexicon_mode']!r}")
    if cfg["veto_mode"] not in (None, "V", "Vd"):
        raise ValueError(f"VETO_MODE 는 None·V·Vd: {cfg['veto_mode']!r}")
    rule, params = cfg["confidence"]["rule"], cfg["confidence"]["params"]
    if rule == "R0" and not params:
        return cfg
    if rule == "R1" and isinstance(params.get("tau"), (int, float)) and set(params) == {"tau"}:
        return cfg
    raise ValueError(f"CONFIDENCE 는 ('R0', {{}}) 또는 ('R1', {{'tau': 숫자}}): {rule!r} {params!r}")


def confidence_rule_text(cfg):
    rule = cfg["confidence"]
    return CONFIDENCE_RULE if rule["rule"] == "R0" else f"{CONFIDENCE_RULE} / {CONFIDENCE_RULE_R1.format(**rule['params'])}"


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
    """순위 기반 임시 규칙(CONFIDENCE_RULE). 한쪽 목록에 아예 없으면(None) 최대 낮음."""
    if rank_tfidf is None or rank_dense is None:
        return "낮음"
    if rank_tfidf == 1 and rank_dense == 1:
        return "높음"
    if (rank_tfidf <= 3 and rank_dense <= 3) or 1 in (rank_tfidf, rank_dense):
        return "보통"
    return "낮음"


def score01(score_rrf, k=RRF_K):
    """Candidate.score: rrf 를 두 목록 모두 1위일 때의 값(2/(k+1))으로 나눠 0~1 로 자른 상대값. 확률이 아니며 근거로 쓰지 않는다."""
    return max(0.0, min(1.0, score_rrf / (2 / (k + 1))))


def match_project(conn, project_id, embedder, progress=lambda done, total: None, digest=(None, None), settings=None):
    """세션의 행을 검색해 match_run 하나를 만든다. 반환: {run_id, queries, cache_hits}. conn 의 트랜잭션 안에서 쓴다.
    settings 를 안 주면 위 상수(current_settings)를 쓴다. 질의 확장·강등·신뢰도는 평가와 같은 함수다(E4a)."""
    from app.evaluation.confidence_rules import judge  # 평가와 같은 함수. confidence_rules 가 이 모듈의 confidence 를 import 하므로 순환을 피하려고 여기서 가져온다
    cfg = check_settings(settings or current_settings())
    items = conn.execute("SELECT query_key, norm_text, input_role, clean_name, clean_spec FROM bom_item WHERE project_id = %s AND norm_text <> '' ORDER BY row_no",
                         (project_id,)).fetchall()
    # 같은 query_key 는 한 번만. 같은 키는 같은 이름이라 구분 추정도 같다
    queries = {key: (text, role, name, spec) for key, text, role, name, spec in items}
    progress(0, len(queries))  # 임베딩이 오래 걸려도 "후보 검색"의 total 이 처음부터 보인다(T9b.2)
    version_id, model_name, idx_items = load_index(conn)  # 작업 시작 때 한 번
    if embedder.model_name != model_name:
        raise RuntimeError(f"인덱스 {version_id}의 모델은 {model_name}인데 임베더는 {embedder.model_name}입니다")
    sn = {it["dataset_id"]: it["list_sn"] for it in idx_items}
    origins = NON_DEV if cfg["lexicon_mode"] == "Ds" else None
    expanded = {key: (expand(q[0], origins) if cfg["lexicon_mode"] else (q[0], q[0], [])) for key, q in queries.items()}  # (밀집 질의, TF-IDF 질의, 적용 항목)
    vectors, hits = embed_queries(embedder, list({e[0] for e in expanded.values()}))
    role_of = dict(conn.execute("SELECT dataset_id, role FROM lci_dataset").fetchall())
    allowed_ids = {role: {d for d, r in role_of.items() if r in codes} for role, codes in ROLE_FILTER.items()}
    v_allowed, v_codes = veto_filters(role_of)

    run_id = f"run-{datetime.now():%Y%m%d%H%M%S}-{secrets.token_hex(3)}"
    lexicon_text = {None: "사전 없음", "D": "사전 D(전체)", "Ds": "사전 Ds(dev 출처 제외)"}[cfg["lexicon_mode"]]
    config = {"top_n": TOP_N, "rrf_k": RRF_K, "search_top": TOP, "ambiguous_rule": AMBIGUOUS_RULE, "confidence_rule": confidence_rule_text(cfg),
              "query": f"norm_text({lexicon_text})", "role_filter_rule": ROLE_FILTER_RULE, "no_answer_rule": NO_ANSWER_RULE,
              "search_base": cfg["search_base"], "lexicon_mode": cfg["lexicon_mode"], "veto_mode": cfg["veto_mode"], "confidence": cfg["confidence"],
              "lexicon": {**origin_counts(), "synonyms_sha256": synonyms_sha256()}}
    model_versions = {"index_version_id": version_id, "embed_model": model_name, "ollama_digest": digest[0],
                      "ollama_digest_error": digest[1], "dim": DIM}
    conn.execute("INSERT INTO match_run (run_id, project_id, config, model_versions) VALUES (%s, %s, %s, %s)",
                 (run_id, project_id, _json(config), _json(model_versions)))
    rule, params = cfg["confidence"]["rule"], cfg["confidence"]["params"]
    rows = []
    for done, (key, (text, role, name, spec)) in enumerate(queries.items(), start=1):
        dense_query, tfidf_query, _ = expanded[key]
        hard = role if role in ROLE_FILTER else None  # 사용자가 구분을 직접 적은 행만 하드 필터(T13)
        veto = None if hard or not cfg["veto_mode"] else effective_role(name)  # 구분이 비면 이름에서 추정한 소재/공정(veto_role)
        allowed, codes = allowed_ids.get(hard), ROLE_FILTER.get(hard)
        if veto and cfg["veto_mode"] == "V":
            allowed, codes = v_allowed[veto], v_codes[veto]
        t = tfidf_rank(idx_items, tfidf_query, TOP, allowed)
        d = dense_rank(conn, version_id, model_name, vectors[dense_query], TOP, codes)
        if veto and cfg["veto_mode"] == "Vd":
            t, d = demote(t, role_of, VETO_EXCLUDE[veto]), demote(d, role_of, VETO_EXCLUDE[veto])
        t_pos = {ds: (r, s) for r, (ds, s) in enumerate(t, 1)}
        d_pos = {ds: (r, s) for r, (ds, s) in enumerate(d, 1)}
        fused = rrf([t, d], sn)
        rrf_score = dict(fused)
        ordered = fused if cfg["search_base"] == "rrf" else [(ds, rrf_score[ds]) for ds, _ in d]  # dense: 밀집 순서, score_rrf 는 두 목록으로 계산한 RRF 점수
        for rank, (ds, s) in enumerate(ordered[:TOP_N], start=1):
            rt, st = t_pos.get(ds, (None, None))
            rd, sd = d_pos.get(ds, (None, None))
            level = judge({"rank_tfidf": rt, "rank_dense": rd, "score_dense": sd}, rule, params)
            rows.append((run_id, key, rank, ds, rt, rd, st, sd, s, level))
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
    run = conn.execute("SELECT run_id, config FROM match_run WHERE project_id = %s ORDER BY started_at DESC LIMIT 1", (project_id,)).fetchone()
    run_cfg = run[1] if run else None  # 옛 run 은 사전·Veto 설정 키가 없다 -> 근거 문구를 더하지 않는다
    keys = list({it["query_key"] for it in items})
    cands = {}
    if run and keys:
        for r in conn.execute(
                "SELECT c.query_key, c.rank, c.dataset_id, c.rank_tfidf, c.rank_dense, c.score_rrf, c.vetoed, c.veto_rule_id, c.confidence, "
                "d.name_ko, d.name_en, d.category, d.developer, d.dev_year, d.version, d.ref_flow_unit, d.has_xml, d.geography, d.allocation, "
                "d.cutoff, d.tech_description, d.list_sn, d.role, d.gwp_total, d.gwp_fossil, d.gwp_biogenic, d.gwp_luluc, d.gwp_method "
                "FROM match_candidate c JOIN lci_dataset d USING (dataset_id) "
                "WHERE c.run_id = %s AND c.query_key = ANY(%s) ORDER BY c.query_key, c.rank", (run[0], keys)).fetchall():
            cands.setdefault(r[0], []).append(dict(zip(
                ["query_key", "rank", "dataset_id", "rank_tfidf", "rank_dense", "score_rrf", "vetoed", "veto_rule_id", "confidence", "name_ko",
                 "name_en", "category", "org", "year", "version", "reference_unit", "has_xml", "geography", "allocation", "cutoff", "tech",
                 "list_sn", "role", "gwp_total", "gwp_fossil", "gwp_biogenic", "gwp_luluc", "gwp_method"], r)))
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
    return [row_payload(it, cands.get(it["query_key"], []), groups, datasets, run_cfg) for it in items]


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


def search_role(input_role, name, spec):
    """검색 필터에 쓰는 구분. 입력 구분이 항상 우선이고, 없을 때만 이름에서 공정을 추정한다(소재 등은 추정해도 필터하지 않는다)."""
    if input_role:
        return input_role
    return "process" if infer_role(name, spec)[0] == "process" else None


def inferred_role_of(it):
    """입력 구분이 없고 이름에서 공정으로 추정되면 표시값 '공정', 아니면 None."""
    if it.get("input_role"):
        return None
    return LABEL["process"] if search_role(None, it.get("clean_name"), it.get("clean_spec")) == "process" else None


def _rank_text(r):
    return f"{r}위" if r else "상위 100위 밖"


def no_answer_reason(c):
    """no_answer 인 행의 대표 후보에 대해 사용자에게 보이는 이유 한 문장."""
    rt, rd = c["rank_tfidf"], c["rank_dense"]
    if rt is None and rd is None:
        return "글자 유사도와 의미 유사도 모두 상위 100위 밖이라 근거가 약합니다"
    if rt is None or rd is None:
        none_side, other_side, other = ("글자", "의미", rd) if rt is None else ("의미", "글자", rt)
        return f"{none_side} 유사도 상위 100위 밖이고 {other_side} 유사도 {other}위뿐이라 근거가 약합니다"
    return f"글자 유사도 {rt}위, 의미 유사도 {rd}위로 순위가 낮아 근거가 약합니다"


def lexicon_line(text, mode):
    """사전이 적중했을 때의 근거 한 줄(적용한 동의어 항목만, 최대 2개). 예: '사전: PP → 폴리프로필렌'. 사전을 안 썼거나 적중이 없으면 None."""
    if not mode:
        return None
    applied = [h for h in expand(text, NON_DEV if mode == "Ds" else None)[2] if "→" in h][:2]
    return "사전: " + ", ".join(h.replace("→", " → ") for h in applied) if applied else None


def reasons_for(c, query, groups, input_role=None, inferred=False, lexicon=None, veto_role_code=None):
    """사실만 적는다. inferred=True 면 input_role 은 이름에서 추정한 값. lexicon 은 lexicon_line 결과,
    veto_role_code 는 강등형 Veto 가 쓴 행의 소재/공정(없으면 None)."""
    rt, rd = c["rank_tfidf"], c["rank_dense"]
    out = [f"글자 유사도 {_rank_text(rt)} · 의미 유사도 {_rank_text(rd)}"]
    group = groups.get(c["name_ko"], [])
    if len(group) > 1:
        latest = newest(group)[0] == c["dataset_id"]
        out.append(f"이름이 같은 데이터셋 {len(group)}건 중 {'최신' if latest else '하나'}")
    name, q = c["name_ko"].replace(" ", "").lower(), query.replace(" ", "").lower()
    if name and q and (name in q or q in name):
        out.append("질의와 이름 부분 일치")
    if input_role in ROLE_FILTER:
        label = LABEL[input_role]
        if inferred:  # 이름에서 추정한 구분은 필터하지 않고 반대 역할 후보를 뒤로 보낸다(E4a 2-1)
            out.append(f"구분 '{label}'을 이름에서 자동 추정")
            out.append(f"{label} 아닌 후보는 뒤로")
        else:  # 사용자가 직접 적은 구분은 하드 필터
            out.append(f"구분 '{label}' → {label} 데이터셋 안에서 찾음")
    if lexicon:
        out.append(lexicon)
    note = demoted_note(veto_role_code, c["role"])
    if note:
        out.append(note)
    if c["role"] == "combined":
        out.append("소재와 공정이 합쳐진 데이터셋 — 같은 부품의 공정 행과 겹치지 않는지 확인")
    return out


def candidate_payload(c, query, groups, input_role=None, inferred=False, lexicon=None, veto_role_code=None):
    group = groups.get(c["name_ko"], [])
    others = [ds for ds, _, _ in sorted(group, key=lambda m: (m[1] is not None, m[1] or 0, m[2]), reverse=True) if ds != c["dataset_id"]]
    return {
        "dataset_id": c["dataset_id"], "name": c["name_ko"], "name_en": c["name_en"], "category": c["category"], "org": c["org"],
        "year": c["year"], "version": version_or_none(c["version"]), "reference_unit": c["reference_unit"], "score": score01(c["score_rrf"]),
        "confidence": c["confidence"], "reasons": reasons_for(c, query, groups, input_role, inferred, lexicon, veto_role_code),
        "veto": {"rule_id": c["veto_rule_id"], "reason": ""} if c["vetoed"] else None,
        "duplicate_group": {"size": len(group), "others": others} if len(group) > 1 else None,
        "role": LABEL.get(c["role"]), "has_xml": c["has_xml"], "geography": c["geography"], "allocation": c["allocation"], "cutoff": c["cutoff"], "tech_summary": c["tech"],
        "carbon": carbon_of(c["gwp_total"], c["gwp_fossil"], c["gwp_biogenic"], c["gwp_luluc"], c["gwp_method"], c["reference_unit"]),
    }


def is_ambiguous(cands):
    """검색 두 방식의 1위가 서로 다른 이름이면 true(AMBIGUOUS_RULE). 한쪽 목록에 후보가 없으면(저장된 후보에 1위가 없으면) false."""
    first_tfidf = next((c["name_ko"] for c in cands if c["rank_tfidf"] == 1), None)
    first_dense = next((c["name_ko"] for c in cands if c["rank_dense"] == 1), None)
    return first_tfidf is not None and first_dense is not None and first_tfidf != first_dense


def num(v):
    return None if v is None else float(v)  # numeric(Decimal) → float


def row_payload(it, cands, groups, datasets=None, run_cfg=None):
    """Row(스펙 07). it 은 ITEM_COLS 의 dict. selected_manual 이 NULL 이면 아직 사람이 선택을 건드리지 않은 행 → 1순위가 기본 선택.
    run_cfg 는 그 행을 검색한 match_run.config(옛 run 이면 None 또는 사전·Veto 키 없음)."""
    datasets = datasets or {}
    cfg = run_cfg or {}
    lexicon = lexicon_line(it["norm_text"], cfg.get("lexicon_mode"))
    veto = effective_role(it.get("clean_name") or "") if cfg.get("veto_mode") == "Vd" and not it.get("input_role") else None
    inferred = inferred_role_of(it)
    eff_role = it.get("input_role") or ("process" if inferred else None)
    folded = fold(cands, groups)
    shown = [candidate_payload(c, it["norm_text"], groups, eff_role, bool(inferred), lexicon, veto) for c in folded]
    no_answer = not shown or shown[0]["confidence"] == NO_ANSWER_CONFIDENCE
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
        "match_state": "no_answer" if no_answer else "candidate",  # NO_ANSWER_RULE
        "no_answer_reason": (no_answer_reason(folded[0]) if shown else "검색된 후보가 없습니다") if no_answer else None,
        "inferred_role": inferred,
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
