"""하이브리드 검색(TF-IDF + 밀집 임베딩, RRF). 실행: uv run --env-file ../.env python -m app.search "질의" [--version ID] [--k 10]

동명 데이터셋은 합치지 않는다(T9). ANN 인덱스 없이 pgvector 정확 비교만 쓴다.
"""
import argparse
import hashlib
import sys
import threading

import psycopg
from sklearn.feature_extraction.text import TfidfVectorizer

from app.db.connection import conninfo
from app.embedder import OllamaEmbedder
from app.indexer import search_text, text_hash, vector_literal

TOP = 100
RRF_K = 60


def load_index(conn, version=None):
    """(버전 id, 모델 이름, 항목 목록). 항목은 lci_dataset 에서 다시 만든 검색 텍스트가 저장된 해시와 같아야 한다."""
    if version:
        v = conn.execute("SELECT version_id, model_name FROM index_version WHERE version_id = %s", (version,)).fetchone()
    else:
        v = conn.execute("SELECT version_id, model_name FROM index_version WHERE active").fetchone()
    if not v:
        raise SystemExit(f"인덱스 버전 {version}을 찾을 수 없습니다" if version else "활성 인덱스가 없습니다. python -m app.indexer --activate 를 먼저 실행하세요")
    rows = conn.execute(
        "SELECT d.dataset_id, d.list_sn, d.name_ko, d.name_en, d.category, i.text_hash FROM lci_dataset d "
        "LEFT JOIN index_version_item i ON i.dataset_id = d.dataset_id AND i.version_id = %s ORDER BY d.list_sn", (v[0],)).fetchall()
    items, stale = [], []
    for dataset_id, sn, ko, en, cat, stored in rows:
        text = search_text(ko, en, cat)
        if stored != text_hash(text):
            stale.append(dataset_id)
        items.append({"dataset_id": dataset_id, "list_sn": sn, "name": ko, "text": text})
    if stale:
        raise SystemExit(f"인덱스가 오래됨: 버전 {v[0]}의 검색 텍스트와 현재 데이터셋이 {len(stale)}건 다릅니다(예: {', '.join(stale[:5])}). "
                         "python -m app.indexer --activate 로 새 버전을 만드세요")
    return v[0], v[1], items


def ordered(scores, sn):
    """점수 내림, 동점이면 list_sn 큰 것이 앞."""
    return sorted(scores, key=lambda d: (-scores[d], -sn[d]))


# 학습한 벡터라이저·행렬 한 벌(프로세스 안에 하나). 키 = 항목 검색 텍스트 목록의 해시. 행렬의 행은 텍스트에만 달려 있으므로
# 항목의 dataset_id·순서가 바뀌어도 텍스트가 같으면 같은 모델이다(점수의 id 대응은 호출마다 현재 항목으로 한다)
_TFIDF = {"key": None, "vec": None, "matrix": None}
_TFIDF_LOCK = threading.Lock()


def tfidf_model(items):
    """전체 항목으로 학습한 (벡터라이저, 행렬). 항목 텍스트가 같으면 다시 학습하지 않는다."""
    texts = [it["text"] for it in items]
    key = hashlib.sha256("\x1f".join(texts).encode("utf-8")).hexdigest()
    with _TFIDF_LOCK:
        if _TFIDF["key"] != key:
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
            _TFIDF.update(key=key, vec=vec, matrix=vec.fit_transform(texts))
        return _TFIDF["vec"], _TFIDF["matrix"]


def tfidf_rank(items, query, top=TOP, allowed=None):
    """allowed(dataset_id 집합)를 주면 그 안에서만 순위를 매긴다. 학습(IDF)은 항상 전체 항목으로 하고, 같은 항목이면 한 번만 한다."""
    vec, matrix = tfidf_model(items)
    sims = (matrix @ vec.transform([query]).T).toarray().ravel()  # 행이 L2 정규화돼 있어 내적 = 코사인
    scores = {it["dataset_id"]: float(s) for it, s in zip(items, sims) if s > 0 and (allowed is None or it["dataset_id"] in allowed)}
    sn = {it["dataset_id"]: it["list_sn"] for it in items}
    return [(d, scores[d]) for d in ordered(scores, sn)[:top]]


def dense_rank(conn, version_id, model_name, query_vector, top=TOP, roles=None):
    """roles(DB 역할 코드 목록)를 주면 그 역할의 데이터셋만 순위에 넣는다(LIMIT 앞에서 거른다)."""
    rows = conn.execute(
        "SELECT i.dataset_id, 1 - (e.vector <=> %s::vector) AS sim FROM index_version_item i "
        "JOIN text_embedding e ON e.text_hash = i.text_hash AND e.model_name = %s JOIN lci_dataset d ON d.dataset_id = i.dataset_id "
        "WHERE i.version_id = %s AND (%s::text[] IS NULL OR d.role = ANY(%s)) ORDER BY e.vector <=> %s::vector, d.list_sn DESC LIMIT %s",
        (vector_literal(query_vector), model_name, version_id, roles, roles, vector_literal(query_vector), top)).fetchall()
    return [(d, float(s)) for d, s in rows]


def rrf(rankings, sn, k=RRF_K):
    """score = Σ 1/(k + rank), rank 는 1부터. 목록에 없는 쪽은 더하지 않는다."""
    scores = {}
    for ranking in rankings:
        for rank, (d, _) in enumerate(ranking, 1):
            scores[d] = scores.get(d, 0.0) + 1.0 / (k + rank)
    return [(d, scores[d]) for d in ordered(scores, sn)]


def search(conn, embedder, query, version=None, k=10):
    version_id, model_name, items = load_index(conn, version)
    if embedder.model_name != model_name:
        raise SystemExit(f"인덱스 {version_id}의 모델은 {model_name}인데 임베더는 {embedder.model_name}입니다")
    sn = {it["dataset_id"]: it["list_sn"] for it in items}
    name = {it["dataset_id"]: it["name"] for it in items}
    tfidf = tfidf_rank(items, query)
    dense = dense_rank(conn, version_id, model_name, embedder.embed([query])[0])
    t_pos = {d: (r, s) for r, (d, s) in enumerate(tfidf, 1)}
    d_pos = {d: (r, s) for r, (d, s) in enumerate(dense, 1)}
    return version_id, [
        {"dataset_id": d, "name": name[d], "tfidf": t_pos.get(d), "dense": d_pos.get(d), "rrf": score}
        for d, score in rrf([tfidf, dense], sn)[:k]
    ]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="하이브리드 검색(TF-IDF + bge-m3, RRF)")
    ap.add_argument("query")
    ap.add_argument("--version")
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args(argv)
    try:
        with psycopg.connect(conninfo()) as conn:
            _, model_name, _ = load_index(conn, args.version)
            version_id, results = search(conn, OllamaEmbedder(model_name.split(":", 1)[-1]), args.query, args.version, args.k)
    except psycopg.OperationalError as e:
        raise SystemExit(f"DB에 접속하지 못했습니다: {e}") from e

    def pos(p):
        return f"{p[0]:>3} {p[1]:.4f}" if p else "  —       "
    print(f"질의 {args.query!r} · 인덱스 {version_id}")
    print(" #  dataset_id  tfidf(순위 점수)  dense(순위 점수)  rrf      이름")
    for i, r in enumerate(results, 1):
        print(f"{i:>2}  {r['dataset_id']:<10}  {pos(r['tfidf'])}       {pos(r['dense'])}       {r['rrf']:.5f}  {r['name']}")


if __name__ == "__main__":
    main()
