"""평가 케이스. 검색 함수(app.search)를 그대로 호출하고 동작은 바꾸지 않는다.

C0 TF-IDF만 · C1 bge-m3 밀집만 · C2 RRF(k=60). C3 사전 · C4 Veto · C5 재순위는 자리만 있고 실행하면 pending.
질의는 bom_text 만 쓴다(spec·unit 은 이후 Veto 용). 질의 임베딩은 한 번에 모아 케이스 사이에 재사용한다.
"""
from app.search import RRF_K, TOP, dense_rank, load_index, rrf, tfidf_rank

CASES = {
    "C0": "TF-IDF만",
    "C1": "bge-m3 밀집만",
    "C2": f"RRF(k={RRF_K})",
    "C3": "사전",
    "C4": "Veto",
    "C5": "재순위",
}
IMPLEMENTED = ("C0", "C1", "C2")


def run_cases(conn, embedder, queries, case_ids, version=None, top=TOP):
    """{case: {"state": "measured"|"pending", "label": ..., "rankings": [[(dataset_id, score), ...] 질의마다] | None}} 와 인덱스 정보."""
    unknown = [c for c in case_ids if c not in CASES]
    if unknown:
        raise SystemExit(f"모르는 케이스: {', '.join(unknown)} (가능: {', '.join(CASES)})")
    version_id, model_name, items = load_index(conn, version)
    if embedder.model_name != model_name:
        raise SystemExit(f"인덱스 {version_id}의 모델은 {model_name}인데 임베더는 {embedder.model_name}입니다")
    sn = {it["dataset_id"]: it["list_sn"] for it in items}
    need_tfidf = any(c in case_ids for c in ("C0", "C2"))
    need_dense = any(c in case_ids for c in ("C1", "C2"))
    tfidf = [tfidf_rank(items, q, top) for q in queries] if need_tfidf else None
    dense = None
    if need_dense:
        vectors = embedder.embed(list(queries)) if queries else []  # 한 번에 모아 배치 처리
        dense = [dense_rank(conn, version_id, model_name, v, top) for v in vectors]
    out = {}
    for c in case_ids:
        if c == "C0":
            rankings = tfidf
        elif c == "C1":
            rankings = dense
        elif c == "C2":
            rankings = [rrf([t, d], sn)[:top] for t, d in zip(tfidf, dense)]
        else:
            out[c] = {"state": "pending", "label": CASES[c], "rankings": None}
            continue
        out[c] = {"state": "measured", "label": CASES[c], "rankings": rankings}
    return out, {"version_id": version_id, "model_name": model_name, "items": items}
