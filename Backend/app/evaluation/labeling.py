"""라벨링 보조. 정답은 사람이 고른다.

  uv run --env-file ../.env python -m app.evaluation.labeling pool <input.csv> --out pool.csv
      input.csv 열: bom_text, input_style, product (spec, unit 선택)
      각 행마다 C0·C1·C2 상위 10의 합집합을 pool.csv(utf-8-sig, 엑셀용)로 쓴다.
      후보는 정답 암시를 줄이려고 점수 순이 아니라 dataset_id(목록 번호) 오름차순.
  uv run python -m app.evaluation.labeling collect pool.csv > gold.csv
      사람이 pick 에 O(또는 no_match 에 O)를 적은 풀을 정답셋 CSV(app.evaluation.gold 형식)로 되돌린다.
"""
import argparse
import csv
import sys

import psycopg

from app.db.connection import conninfo
from app.embedder import OllamaEmbedder
from app.evaluation.cases import run_cases
from app.evaluation.gold import COLUMNS

POOL_COLS = ["row_id", "bom_text", "candidate_rank_c0", "candidate_rank_c1", "candidate_rank_c2", "dataset_id", "name_ko", "name_en", "org",
             "year", "has_xml", "pick", "no_match", "input_style", "product", "spec", "unit"]  # 뒤 4열은 collect 가 되돌릴 때 쓴다
TOP_POOL = 10
MARKS = {"o", "y", "1", "v", "x"}  # pick·no_match 칸에 표시로 인정하는 글자(대소문자 무시)


def sn_of(dataset_id):
    return int(dataset_id.split("-", 1)[1])


def read_input(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [{k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]
    bad = [i for i, r in enumerate(rows, start=2) if not r.get("bom_text") or not r.get("input_style")]
    if bad:
        raise SystemExit(f"bom_text·input_style 이 비어 있는 행: {', '.join(map(str, bad))}")
    return rows


def build_pool(conn, embedder, rows):
    """풀 행 목록. 같은 입력 행 안에서는 dataset_id 의 목록 번호 오름차순(점수 순 아님)."""
    results, _ = run_cases(conn, embedder, [r["bom_text"] for r in rows], ["C0", "C1", "C2"], top=TOP_POOL)
    ids = sorted({d for c in results.values() for ranking in c["rankings"] for d, _ in ranking}, key=sn_of)
    meta = {}
    if ids:
        for d, ko, en, org, year, xml in conn.execute(
                "SELECT dataset_id, name_ko, name_en, developer, dev_year, has_xml FROM lci_dataset WHERE dataset_id = ANY(%s)", (ids,)).fetchall():
            meta[d] = {"name_ko": ko, "name_en": en, "org": org, "year": year, "has_xml": "Y" if xml else "N"}
    pool = []
    for i, r in enumerate(rows):
        pos = {c: {d: rank for rank, (d, _) in enumerate(results[c]["rankings"][i], 1)} for c in ("C0", "C1", "C2")}
        for d in sorted(set().union(*(p.keys() for p in pos.values())), key=sn_of):
            pool.append({"row_id": i + 1, "bom_text": r["bom_text"],
                         "candidate_rank_c0": pos["C0"].get(d, ""), "candidate_rank_c1": pos["C1"].get(d, ""), "candidate_rank_c2": pos["C2"].get(d, ""),
                         "dataset_id": d, **meta.get(d, {}), "pick": "", "no_match": "",
                         "input_style": r["input_style"], "product": r.get("product", ""), "spec": r.get("spec", ""), "unit": r.get("unit", "")})
    return pool


def collect(pool_rows):
    """(정답셋 행 목록, 오류 목록). 한 입력 행에 pick 이 둘 이상이거나 pick 과 no_match 가 같이 있으면 오류."""
    by_row = {}
    for p in pool_rows:
        by_row.setdefault(p["row_id"], []).append(p)
    out, errors = [], []
    for row_id, ps in sorted(by_row.items(), key=lambda kv: int(kv[0])):
        first = ps[0]
        picks = [p["dataset_id"] for p in ps if (p.get("pick") or "").strip().lower() in MARKS]
        no_match = any((p.get("no_match") or "").strip().lower() in MARKS for p in ps)
        base = {c: "" for c in COLUMNS} | {"bom_text": first["bom_text"], "spec": first.get("spec", ""), "unit": first.get("unit", ""),
                                           "input_style": first.get("input_style", ""), "product": first.get("product", "")}
        if len(picks) > 1 or (picks and no_match):
            errors.append(f"row_id {row_id}: pick {len(picks)}개{' + no_match' if no_match else ''} — 하나만 표시하세요")
            continue
        if picks:
            out.append(base | {"expected_dataset_id": picks[0], "is_no_match": "0", "label_source": "pool"})
        elif no_match:
            out.append(base | {"is_no_match": "1", "label_source": "pool"})
        else:  # 풀에 정답이 없으면 사람이 manual 로 직접 적는다(비워 두면 gold validate 가 오류로 알려 준다)
            out.append(base | {"label_source": "manual", "note": "풀에 정답 없음: expected_dataset_id 를 직접 적거나 is_no_match=1"})
    return out, errors


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="라벨링 풀 생성·회수")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pool")
    p.add_argument("input")
    p.add_argument("--out", required=True)
    c = sub.add_parser("collect")
    c.add_argument("pool")
    args = ap.parse_args(argv)

    if args.cmd == "pool":
        rows = read_input(args.input)
        with psycopg.connect(conninfo()) as conn:
            model = conn.execute("SELECT model_name FROM index_version WHERE active").fetchone()
            embedder = OllamaEmbedder((model[0] if model else "ollama:bge-m3").split(":", 1)[-1])
            pool = build_pool(conn, embedder, rows)
        with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=POOL_COLS)
            w.writeheader()
            w.writerows(pool)
        print(f"{args.out}: 입력 {len(rows)}행, 후보 {len(pool)}줄")
        return
    with open(args.pool, encoding="utf-8-sig", newline="") as f:
        out, errors = collect(list(csv.DictReader(f)))
    if errors:
        raise SystemExit("\n".join(errors))
    w = csv.DictWriter(sys.stdout, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(out)


if __name__ == "__main__":
    main()
