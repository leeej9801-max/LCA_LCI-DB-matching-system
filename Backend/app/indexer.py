"""검색 인덱스 버전 만들기. 실행: uv run --env-file ../.env python -m app.indexer [--model bge-m3] [--activate] [--dry-run]

검색 텍스트는 원본 필드만(국문명 | 영문명 | 분류). 임베딩은 (text_hash, model_name)당 한 번만 계산해 text_embedding 에 둔다.
한 트랜잭션으로 index_version·index_version_item 을 쓰고, 실패하거나 --dry-run 이면 아무것도 남기지 않는다.
"""
import argparse
import hashlib
import sys
import time
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from app.db.connection import conninfo
from app.embedder import BATCH, DIM, OllamaEmbedder


def search_text(name_ko, name_en, category):
    """원본 필드만 ' | '로 잇는다. 빈 값은 빼서 빈 칸 흔적(' |  | ')이 남지 않게 한다."""
    return " | ".join(p.strip() for p in (name_ko, name_en, category) if p and p.strip())


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_literal(v):
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def dataset_texts(conn):
    """[(dataset_id, 검색 텍스트, 해시)] list_sn 순서."""
    rows = conn.execute("SELECT dataset_id, name_ko, name_en, category FROM lci_dataset ORDER BY list_sn").fetchall()
    return [(r[0], t, text_hash(t)) for r in rows for t in [search_text(r[1], r[2], r[3])]]


def build_index(conninfo_, embedder, activate=False, dry_run=False, now=None, log=print):
    """새 인덱스 버전을 만든다. 요약 dict 를 돌려준다(변경 없으면 {"unchanged": True, ...})."""
    started = time.perf_counter()
    model = embedder.model_name
    with psycopg.connect(conninfo_) as conn:
        with conn.transaction(force_rollback=dry_run):
            items = dataset_texts(conn)
            hashes = {d: h for d, _, h in items}

            # 직전 활성 버전과 모델·데이터셋별 해시가 모두 같으면 새 버전을 만들지 않는다
            active = conn.execute("SELECT version_id, model_name FROM index_version WHERE active").fetchone()
            if active and active[1] == model:
                prev = dict(conn.execute("SELECT dataset_id, text_hash FROM index_version_item WHERE version_id = %s",
                                         (active[0],)).fetchall())
                if prev == hashes:
                    return {"unchanged": True, "version_id": active[0], "datasets": len(items)}

            distinct = {h: t for _, t, h in items}
            have = {r[0] for r in conn.execute("SELECT text_hash FROM text_embedding WHERE model_name = %s AND text_hash = ANY(%s)",
                                                 (model, list(distinct))).fetchall()}
            new = [h for h in distinct if h not in have]
            log(f"데이터셋 {len(items)}, 서로 다른 텍스트 {len(distinct)}, 새로 임베딩 {len(new)}, 재사용 {len(distinct) - len(new)}")
            embed_started = time.perf_counter()
            for i in range(0, len(new), BATCH):
                chunk = new[i:i + BATCH]
                vectors = embedder.embed([distinct[h] for h in chunk])
                if len(vectors) != len(chunk) or any(len(v) != DIM for v in vectors):
                    raise SystemExit(f"임베딩 차원·개수가 맞지 않습니다(필요: {DIM}차원 × {len(chunk)}개)")
                with conn.cursor() as cur:
                    cur.executemany("INSERT INTO text_embedding (text_hash, model_name, vector) VALUES (%s, %s, %s::vector)",
                                    [(h, model, vector_literal(v)) for h, v in zip(chunk, vectors)])
                log(f"  임베딩 {min(i + BATCH, len(new))}/{len(new)}")
            embed_seconds = time.perf_counter() - embed_started

            stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
            base = f"idx-{stamp}-{model.split(':')[-1]}"
            version_id, n = base, 1
            while conn.execute("SELECT 1 FROM index_version WHERE version_id = %s", (version_id,)).fetchone():
                n += 1
                version_id = f"{base}-{n}"
            stats = {"datasets": len(items), "distinct_texts": len(distinct), "embedded_new": len(new),
                     "reused": len(distinct) - len(new), "seconds": round(time.perf_counter() - started, 2),
                     "embed_seconds": round(embed_seconds, 2), "model": model, "dim": DIM,
                     # 재현성: 임베딩 모델 파일의 digest(Ollama). 임베더가 지원하지 않으면 None
                     "model_digest": embedder.model_digest()[0] if hasattr(embedder, "model_digest") else None}
            conn.execute("INSERT INTO index_version (version_id, model_name, active, stats) VALUES (%s, %s, false, %s)",
                         (version_id, model, Jsonb(stats)))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO index_version_item (version_id, dataset_id, text_hash) VALUES (%s, %s, %s)",
                                [(version_id, d, h) for d, _, h in items])
            if activate:
                conn.execute("UPDATE index_version SET active = false WHERE active")
                conn.execute("UPDATE index_version SET active = true WHERE version_id = %s", (version_id,))
    return {"unchanged": False, "version_id": version_id, "activated": activate, "dry_run": dry_run, **stats}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="검색 인덱스 버전 만들기")
    ap.add_argument("--model", default="bge-m3", help="Ollama 임베딩 모델")
    ap.add_argument("--activate", action="store_true", help="같은 트랜잭션에서 이 버전을 활성으로")
    ap.add_argument("--dry-run", action="store_true", help="계산 후 롤백")
    args = ap.parse_args(argv)
    try:
        s = build_index(conninfo(), OllamaEmbedder(args.model), activate=args.activate, dry_run=args.dry_run)
    except psycopg.OperationalError as e:
        raise SystemExit(f"DB에 접속하지 못했습니다: {e}") from e
    if s["unchanged"]:
        print(f"변경 없음: 활성 버전 {s['version_id']}와 모델·데이터셋별 해시가 같습니다")
        return
    state = "dry-run(롤백함)" if s["dry_run"] else ("활성으로 저장" if s["activated"] else "저장(비활성)")
    print(f"{s['version_id']} {state}: 데이터셋 {s['datasets']}, 서로 다른 텍스트 {s['distinct_texts']}, "
          f"새로 임베딩 {s['embedded_new']}, 재사용 {s['reused']}, 임베딩 {s['embed_seconds']}초, 전체 {s['seconds']}초")


if __name__ == "__main__":
    main()
