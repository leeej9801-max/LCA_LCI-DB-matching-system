"""데이터셋 역할(lci_dataset.role). 실행: uv run --env-file ../.env python -m app.roles apply

규칙: ① 시드 CSV(app/data/dataset_roles.csv)에 이름이 있으면 그 역할(공정·합본만 사람이 골랐다) ② 분류 규칙 ③ 나머지는 소재.
검색 텍스트·인덱스 해시는 바꾸지 않는다(역할은 필터에만 쓴다). 분류표 docs/LCA/data/dataset-roles-2026-10-18.csv 에서 뽑아 만든 시드다.
"""
import csv
import sys
from pathlib import Path

import psycopg

from app.db.connection import conninfo

SEED = Path(__file__).resolve().parent / "data" / "dataset_roles.csv"
# DB 코드(영문, 마이그레이션은 ASCII) ↔ API 표시값(한글)
LABEL = {"material": "소재", "process": "공정", "combined": "합본", "transport": "수송", "waste": "폐기·재활용", "utility": "에너지·유틸리티"}
CODE = {v: k for k, v in LABEL.items()}
CATEGORY_RULE = {
    "수송": "transport", "폐기물 처리& 재활용": "waste",
    "전기": "utility", "연료": "utility", "열": "utility", "수자원": "utility", "인프라 & 기계": "utility",
}


def load_seed(path=SEED):
    with open(path, encoding="utf-8", newline="") as f:
        return {r["name_ko"]: CODE[r["role"]] for r in csv.DictReader(f)}


def role_of(name_ko, category, seed):
    return seed.get(name_ko) or CATEGORY_RULE.get(category) or "material"


def apply(conn, dataset_ids=None):
    """역할을 채운다(멱등). dataset_ids 가 None 이면 전체. 바꾼 행 수를 돌려준다."""
    seed = load_seed()
    rows = conn.execute("SELECT dataset_id, name_ko, category, role FROM lci_dataset WHERE %s::text[] IS NULL OR dataset_id = ANY(%s)",
                        (dataset_ids, dataset_ids)).fetchall()
    changed = [(role_of(n, c, seed), d) for d, n, c, old in rows if role_of(n, c, seed) != old]
    with conn.cursor() as cur:
        cur.executemany("UPDATE lci_dataset SET role = %s WHERE dataset_id = %s", changed)
    return len(changed)


def counts(conn):
    return dict(conn.execute("SELECT coalesce(role, 'NULL'), count(*) FROM lci_dataset GROUP BY 1").fetchall())


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    if (argv if argv is not None else sys.argv[1:]) != ["apply"]:
        raise SystemExit("사용법: python -m app.roles apply")
    with psycopg.connect(conninfo()) as conn:
        n = apply(conn)
        c = counts(conn)
    print(f"역할을 바꾼 행 {n}건")
    for code, label in LABEL.items():
        print(f"  {label}: {c.get(code, 0)}")
    print(f"  NULL: {c.get('NULL', 0)}")
    if c.get("NULL"):
        raise SystemExit("role 이 NULL 인 행이 남았습니다")


if __name__ == "__main__":
    main()
