"""정답셋 CSV 검증·적재. 정답 내용은 사용자가 채운다(이 모듈은 형식만 본다).

  uv run --env-file ../.env python -m app.evaluation.gold validate <csv>
  uv run --env-file ../.env python -m app.evaluation.gold load <csv> --name 이름 --version v1
  uv run python -m app.evaluation.gold template   # 헤더만 있는 빈 CSV 를 stdout 으로
"""
import argparse
import csv
import hashlib
import io
import random
import sys
from pathlib import Path

import psycopg

from app.db.connection import conninfo

COLUMNS = ["bom_text", "spec", "unit", "expected_dataset_id", "is_no_match", "hard_pair_group", "input_style", "product",
           "label_source", "split", "source", "note"]
SEED = 42


def read_csv(path):
    """(바이트 sha256, [(행 번호, dict)]). 행 번호는 헤더를 1행으로 센 파일 기준."""
    data = Path(path).read_bytes()
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = [(i, {k: (v or "").strip() for k, v in r.items() if k is not None}) for i, r in enumerate(reader, start=2)]
    return hashlib.sha256(data).hexdigest(), reader.fieldnames or [], rows


def validate(header, rows, known_ids):
    """오류 [(행 번호 또는 None, 메시지)]를 한꺼번에 모은다. known_ids: lci_dataset 의 dataset_id 집합."""
    errors = []
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        return [(None, f"필수 열이 없습니다: {', '.join(missing)}")]
    seen = {}
    for n, r in rows:
        if not r["bom_text"]:
            errors.append((n, "bom_text 가 비어 있습니다"))
        elif r["bom_text"] in seen:
            errors.append((n, f"bom_text 중복: {seen[r['bom_text']]}행과 같습니다 ({r['bom_text']!r})"))
        else:
            seen[r["bom_text"]] = n
        if r["is_no_match"] not in ("", "0", "1"):
            errors.append((n, f"is_no_match 는 0 또는 1 이어야 합니다: {r['is_no_match']!r}"))
        no_match = r["is_no_match"] == "1"
        if no_match and r["expected_dataset_id"]:
            errors.append((n, "is_no_match=1 인데 expected_dataset_id 가 있습니다(둘 중 하나만)"))
        if not no_match and not r["expected_dataset_id"]:
            errors.append((n, "expected_dataset_id 가 비어 있습니다(정답이 없으면 is_no_match=1)"))
        if r["expected_dataset_id"] and r["expected_dataset_id"] not in known_ids:
            errors.append((n, f"lci_dataset 에 없는 dataset_id: {r['expected_dataset_id']}"))
        if r["split"] not in ("", "dev", "test"):
            errors.append((n, f"split 은 dev·test·빈칸 중 하나: {r['split']!r}"))
        if not r["input_style"]:
            errors.append((n, "input_style 이 비어 있습니다"))
        if r["label_source"] not in ("", "pool", "manual"):
            errors.append((n, f"label_source 는 pool·manual·빈칸 중 하나: {r['label_source']!r}"))
    return errors


def assign_splits(rows, seed=SEED):
    """split 이 빈 행에 dev/test 를 배정한다: input_style 별로 시드 고정 섞기 후 번갈아(dev 부터). 결과는 {행 번호: split}."""
    out = {n: r["split"] for n, r in rows if r["split"]}
    by_style = {}
    for n, r in rows:
        if not r["split"]:
            by_style.setdefault(r["input_style"], []).append(n)
    rng = random.Random(seed)
    for style in sorted(by_style):
        ns = sorted(by_style[style])
        rng.shuffle(ns)
        for i, n in enumerate(ns):
            out[n] = "dev" if i % 2 == 0 else "test"
    return out


def known_dataset_ids(conn):
    return {r[0] for r in conn.execute("SELECT dataset_id FROM lci_dataset").fetchall()}


def format_errors(errors):
    return "\n".join(f"  {f'{n}행' if n else '파일'}: {msg}" for n, msg in errors)


def load(conninfo_, path, name, version):
    """적재하고 gold_id 를 돌려준다. 같은 파일(sha256)이 이미 있으면 새로 만들지 않고 그 gold_id 를 돌려준다."""
    sha, header, rows = read_csv(path)
    with psycopg.connect(conninfo_) as conn:
        existing = conn.execute("SELECT gold_id FROM gold_set WHERE sha256 = %s", (sha,)).fetchone()
        if existing:
            return existing[0], False
        errors = validate(header, rows, known_dataset_ids(conn))
        if errors:
            raise SystemExit(f"정답셋 오류 {len(errors)}건 — 적재하지 않았습니다\n{format_errors(errors)}")
        gold_id = f"gold-{name}-{version}"
        if conn.execute("SELECT 1 FROM gold_set WHERE gold_id = %s", (gold_id,)).fetchone():
            raise SystemExit(f"{gold_id} 가 이미 있고 파일 내용이 다릅니다. --version 을 바꾸세요")
        splits = assign_splits(rows)
        with conn.transaction():
            conn.execute("INSERT INTO gold_set (gold_id, name, version, sha256) VALUES (%s, %s, %s, %s)", (gold_id, name, version, sha))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO gold_label (gold_id, bom_text, spec, unit, expected_dataset_id, is_no_match, hard_pair_group, product, "
                    "input_style, label_source, split, source, note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    [(gold_id, r["bom_text"], r["spec"] or None, r["unit"] or None, r["expected_dataset_id"] or None,
                      1 if r["is_no_match"] == "1" else 0, r["hard_pair_group"] or None, r["product"] or None, r["input_style"],
                      r["label_source"] or None, splits[n], r["source"] or None, r["note"] or None) for n, r in rows])
    return gold_id, True


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="정답셋 CSV 검증·적재")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("csv")
    lo = sub.add_parser("load")
    lo.add_argument("csv")
    lo.add_argument("--name", required=True)
    lo.add_argument("--version", required=True)
    sub.add_parser("template")
    args = ap.parse_args(argv)

    if args.cmd == "template":
        csv.writer(sys.stdout, lineterminator="\n").writerow(COLUMNS)
        return
    if args.cmd == "validate":
        _, header, rows = read_csv(args.csv)
        with psycopg.connect(conninfo()) as conn:
            errors = validate(header, rows, known_dataset_ids(conn))
        if errors:
            raise SystemExit(f"오류 {len(errors)}건\n{format_errors(errors)}")
        splits = assign_splits(rows)
        print(f"오류 없음: {len(rows)}행 (정답 없음 {sum(r['is_no_match'] == '1' for _, r in rows)}행, "
              f"dev {sum(s == 'dev' for s in splits.values())} / test {sum(s == 'test' for s in splits.values())})")
        return
    gold_id, created = load(conninfo(), args.csv, args.name, args.version)
    print(f"{gold_id} {'적재함' if created else '같은 파일(sha256)이 이미 있어 그대로 둠'}")


if __name__ == "__main__":
    main()
