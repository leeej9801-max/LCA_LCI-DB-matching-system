"""평가 케이스. 검색 함수(app.search)를 그대로 호출하고 동작은 바꾸지 않는다.

기준 케이스: C0 TF-IDF만 · C1 bge-m3 밀집만 · C2 RRF(k=60).
요소(E2, 기준 뒤에 '+'로 붙인다. 순서는 표기에서 G·D·V·X 로 맞춘다):
  G 동명 접기 — 앱의 app.bom.match.fold 를 import 해 순위에 적용(같은 이름은 최신 판 대표 하나)
  D 사전 — app.bom.lexicon.expand(밀집 질의 = 원문+덧붙임, TF-IDF 질의 = 거기서 형태어를 뺀 것)
  Ds 사전에서 출처가 dev 인 항목을 뺀 것(E2b). D 와 함께 쓰지 못한다. dev 에서 본 향상 중 과적합 가능분을 가르는 비교용
  V Veto — app.bom.infer_role.veto_role 로 소재/공정을 추정해 반대 역할 데이터셋을 순위 전에 뺀다(합본은 빼지 않는다)
  Vd Veto 강등(E2b) — 빼지 않고 반대 역할 후보를 모두 뒤로 보낸다(각 묶음 안의 기존 순서 유지, 합본 불변). V 와 함께 쓰지 못한다
  X:<run_id> 외부 결과 — 가져온 run(eval_external_result)의 ranking 을 순위로 쓴다. judge 의 decision='none' 은 no_answer
자리 이름: C3 = C2+D, C4 = C2+D+V, C5 = C4+X:<run_id>(run_id 없이 'C5'만 쓰면 pending).
질의는 bom_text 만 쓴다. 질의 임베딩은 한 번에 모아 케이스 사이에 재사용한다.
"""
from app.bom.lexicon import NON_DEV, expand
from app.bom.match import fold
from app.bom.veto import VETO_EXCLUDE, demote, effective_role, veto_filters  # noqa: F401  (앱과 같은 함수. 시험·리포트가 여기서도 가져다 쓴다)
from app.search import RRF_K, TOP, dense_rank, load_index, rrf, tfidf_rank

BASES = {"C0": "TF-IDF만", "C1": "bge-m3 밀집만", "C2": f"RRF(k={RRF_K})"}
ELEMENTS = {"G": "동명 접기", "D": "사전", "Ds": "사전(dev 출처 제외)", "V": "Veto", "Vd": "Veto 강등", "X": "외부 결과"}
ORDER = ("G", "D", "Ds", "V", "Vd")  # 표기 순서
ALIASES = {"C3": "C2+D", "C4": "C2+D+V"}
CASES = {**BASES, "C3": "사전 (C2+D)", "C4": "사전+Veto (C2+D+V)", "C5": "재순위 (C4+X:<run_id>)"}
IMPLEMENTED = ("C0", "C1", "C2", "C3", "C4")
LADDER = ("C0", "C1", "C2", "C2+D", "C2+D+V")  # 리포트 ablation 누적 순서(C5 는 C2+D+V+X:… 로 그 뒤)


def modes(p):
    """(사전 모드 None|'D'|'Ds', Veto 모드 None|'V'|'Vd')."""
    e = p["elements"]
    return ("Ds" if "Ds" in e else "D" if "D" in e else None), ("Vd" if "Vd" in e else "V" if "V" in e else None)


def parse_case(spec):
    """{spec, canonical, base, elements(set G·D·Ds·V·Vd), run(외부 run_id|None), pending}. 모르는 표기는 SystemExit."""
    s = spec.strip()
    if s == "C5":
        return {"spec": s, "canonical": s, "base": None, "elements": set(), "run": None, "pending": True}
    parts = s.split("+")
    if parts[0] in ALIASES:
        parts = ALIASES[parts[0]].split("+") + parts[1:]
    if parts[0] not in BASES:
        raise SystemExit(f"모르는 케이스: {s} (기준: {', '.join(BASES)} 또는 {', '.join(ALIASES)}·C5, 요소: G·D·Ds·V·Vd·X:<run_id>)")
    elements, run = set(), None
    for p in parts[1:]:
        if p in ORDER:
            elements.add(p)
        elif p.startswith("X:") and len(p) > 2 and run is None:
            run = p[2:]
        else:
            raise SystemExit(f"모르는 케이스 요소: {p!r} in {s} (가능: G·D·Ds·V·Vd·X:<run_id>)")
    for a, b in (("D", "Ds"), ("V", "Vd")):
        if a in elements and b in elements:
            raise SystemExit(f"{a} 와 {b} 는 함께 쓰지 못합니다: {s}")
    canonical = "+".join([parts[0]] + [e for e in ORDER if e in elements] + ([f"X:{run}"] if run else []))
    return {"spec": s, "canonical": canonical, "base": parts[0], "elements": elements, "run": run, "pending": False}


def label_of(p):
    if p["pending"]:
        return CASES["C5"] + " — run_id 필요"
    alias = next((a for a, full in ALIASES.items() if full == p["canonical"]), None)
    text = " + ".join([BASES[p["base"]]] + [ELEMENTS[e] for e in ORDER if e in p["elements"]] + ([f"외부 {p['run']}"] if p["run"] else []))
    return f"{text} (= {alias})" if alias else text


def ladder_key(spec):
    """ablation 정렬 키: LADDER 순서, 그 밖은 뒤에(입력 순서 유지는 sorted 의 안정성으로)."""
    canon = spec if spec == "C5" else parse_case(spec)["canonical"]
    base_ladder = canon.split("+X:")[0]
    return (LADDER.index(base_ladder) if base_ladder in LADDER else len(LADDER), "+X:" in canon)


def base_without_x(p):
    """X 를 뺀 D·Ds·V·Vd 부분(외부 결과를 만든 내보내기의 base_case 와 비교). G 는 순위 뒤에 접으므로 비교에서 뺀다."""
    return "+".join([p["base"]] + [e for e in ("D", "Ds", "V", "Vd") if e in p["elements"]])


def fold_ranking(ranking, catalog):
    """앱과 같은 fold 로 동명 후보를 접은 순위. 점수는 그 이름이 처음 나온 자리의 점수."""
    cands = [{"dataset_id": d, "name_ko": catalog[d][0], "year": catalog[d][1], "list_sn": catalog[d][2]} for d, _ in ranking]
    groups = {}  # 앱(build_rows)과 같은 모양: name_ko → [(dataset_id, year, list_sn)]
    for d, (name, year, sn) in catalog.items():
        groups.setdefault(name, []).append((d, year, sn))
    head = {}
    for d, s in ranking:
        head.setdefault(catalog[d][0], s)
    return [(c["dataset_id"], head[c["name_ko"]]) for c in fold(cands, groups, n=len(cands))]


def run_cases(conn, embedder, queries, case_ids, version=None, top=TOP, label_ids=None):
    """{case: {state, label, canonical, rankings, tfidf, dense, meta, veto_changed, decisions, external}} 와 인덱스 정보.
    tfidf·dense 는 그 케이스가 쓴 두 목록(사전·Veto 적용 뒤) — 신뢰도 판정에 쓴다. 외부 결과(X)는 label_ids 가 필요하다."""
    parsed = {c: parse_case(c) for c in case_ids}
    version_id, model_name, items = load_index(conn, version)
    if embedder.model_name != model_name:
        raise SystemExit(f"인덱스 {version_id}의 모델은 {model_name}인데 임베더는 {embedder.model_name}입니다")
    sn = {it["dataset_id"]: it["list_sn"] for it in items}
    live = [p for p in parsed.values() if not p["pending"]]
    variants = {modes(p) for p in live}
    variants |= {(d, None) for d, v in variants if v}  # Veto 전 목록(Vd 의 재료, veto_changed·순위 하락 비교)
    needs_v = any(v for _, v in variants)
    catalog = role_of = None
    if needs_v:
        role_of = dict(conn.execute("SELECT dataset_id, role FROM lci_dataset").fetchall())
    if any("G" in p["elements"] for p in live):
        catalog = {d: (n, y, s) for d, n, y, s in conn.execute("SELECT dataset_id, name_ko, dev_year, list_sn FROM lci_dataset").fetchall()}

    prepared = {}  # (사전 모드, Veto 모드) → 질의마다 (밀집 질의, TF-IDF 질의, 사전 항목, 추정 역할)
    for d, v in variants:
        rows = []
        for q in queries:
            dq, tq, hits = expand(q, NON_DEV if d == "Ds" else None) if d else (q, q, [])
            rows.append((dq, tq, hits, effective_role(q) if v else None))
        prepared[(d, v)] = rows
    texts = list(dict.fromkeys(dq for rows in prepared.values() for dq, *_ in rows))
    vectors = dict(zip(texts, embedder.embed(texts))) if texts else {}  # 한 번에 모아 배치 처리
    allowed, role_codes = veto_filters(role_of) if needs_v else ({}, {})
    lists = {}
    for (d, v), rows in prepared.items():
        if v == "Vd":
            continue
        lists[(d, v)] = ([tfidf_rank(items, tq, top, allowed.get(role) if v else None) for _, tq, _, role in rows],
                         [dense_rank(conn, version_id, model_name, vectors[dq], top, role_codes.get(role) if v else None) for dq, _, _, role in rows])
    for (d, v), rows in prepared.items():  # 강등형: 필터 없는 목록에서 반대 역할을 뒤로
        if v == "Vd":
            t0, d0 = lists[(d, None)]
            ex = [VETO_EXCLUDE.get(role) for *_, role in rows]
            lists[(d, v)] = ([demote(r, role_of, e) if e else r for r, e in zip(t0, ex)], [demote(r, role_of, e) if e else r for r, e in zip(d0, ex)])

    def fused(base, t, dn):
        if base == "C0":
            return t
        return dn if base == "C1" else [rrf([a, b], sn)[:top] for a, b in zip(t, dn)]

    out = {}
    for c, p in parsed.items():
        if p["pending"]:
            out[c] = {"state": "pending", "label": label_of(p), "canonical": p["canonical"], "rankings": None}
            continue
        key = modes(p)
        t, dn = lists[key]
        rankings = fused(p["base"], t, dn)
        decisions = external = None
        if p["run"]:
            rankings, decisions, external = external_rankings(conn, p, label_ids)
        if "G" in p["elements"]:
            rankings = [fold_ranking(r, catalog) for r in rankings]
        changed = before = None
        if key[1]:
            before = fused(p["base"], *lists[(key[0], None)])
            if "G" in p["elements"]:
                before = [fold_ranking(r, catalog) for r in before]
            changed = [(a[0][0] if a else None) != (b[0][0] if b else None) for a, b in zip(rankings, before)]
        meta = [{"query_expanded": dq if key[0] else None, "lexicon_hits": hits, "inferred_role": role} for dq, _, hits, role in prepared[key]]
        out[c] = {"state": "measured", "label": label_of(p), "canonical": p["canonical"], "rankings": rankings, "tfidf": t, "dense": dn,
                  "meta": meta, "veto_changed": changed, "before_veto": before, "decisions": decisions, "external": external,
                  "lexicon_mode": key[0]}
    return out, {"version_id": version_id, "model_name": model_name, "items": items}


def external_rankings(conn, p, label_ids):
    """(rankings, decisions, run 정보). 내보내기의 base_case 가 이 케이스의 D·V 부분과 같아야 하고, 모든 행의 결과가 있어야 한다."""
    if label_ids is None:
        raise SystemExit("외부 결과(X) 케이스는 label_ids 가 필요합니다")
    run = conn.execute(
        "SELECT r.run_id, r.kind, r.model, r.params, r.structure, r.prompt_sha256, e.export_id, e.base_case FROM eval_external_run r "
        "JOIN eval_export e USING (export_id) WHERE r.run_id = %s", (p["run"],)).fetchone()
    if not run:
        raise SystemExit(f"외부 결과 run {p['run']} 이 없습니다. python -m app.evaluation.import_external 로 먼저 가져오세요")
    run_id, kind, model, params, structure, prompt_sha, export_id, base_case = run
    # G 는 순위 뒤 접기라 기준 비교에서 양쪽 모두 뺀다(내보내기 base_case 에는 G 가 남아 있을 수 있다)
    if base_without_x(parse_case(base_case)) != base_without_x(p):
        raise SystemExit(f"run {run_id} 은 {base_case} 의 후보로 만든 결과입니다. 케이스 {p['spec']} 의 기준({base_without_x(p)})과 다릅니다")
    got = {lid: (ranking, decision) for lid, ranking, decision in conn.execute(
        "SELECT label_id, ranking, decision FROM eval_external_result WHERE run_id = %s", (run_id,)).fetchall()}
    missing = [lid for lid in label_ids if lid not in got]
    if missing:
        raise SystemExit(f"run {run_id} 에 결과가 없는 행 {len(missing)}개(예: {missing[:5]}). 같은 정답셋·분할로 내보낸 결과인지 확인하세요")
    rankings = [[(d, float(s)) for d, s in got[lid][0]] for lid in label_ids]
    decisions = [got[lid][1] for lid in label_ids] if kind == "judge" else None
    return rankings, decisions, {"run_id": run_id, "kind": kind, "model": model, "params": params, "structure": structure,
                                 "prompt_sha256": prompt_sha, "export_id": export_id, "base_case": base_case}
