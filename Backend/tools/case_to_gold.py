"""사례 세트(gold-draft)를 정답셋 계약 CSV(app.evaluation.gold 형식, F3 확장 열 포함)로 바꾼다. DB 없이 돈다.

실행(Backend에서):
  uv run python -m tools.case_to_gold --in ../docs/LCA/data/gold-draft-2026-10-18.csv --out ../docs/LCA/data/gold/case-v2.csv --source case-v2

변환 뒤 엄격(S) 기준을 정규화한다(동명은 최신 판만 S, E1b). 바뀐 행은 decided_by=user, note 에 NORMALIZE_NOTE 를 붙이고 목록을 출력한다.

flags 는 ';' 로 구분한다. 읽는 것: A_accept=list-1,list-2 · S_accept=list-1,list-2 · S_accept=none(또는 'S none') = 엄격 기준 허용 없음.
그 밖의 flag 는 해석하지 않고 건너뛰며, 끝에 목록으로 출력한다.
기본값: A_accept 가 없으면 [label_dataset_id]. S_accept 가 없으면 exact 는 [label_dataset_id], proxy 는 빈 목록(엄격 기준으로 맞는 것 없음).
input_style 은 사례 세트에 없는 값이라 '사례' 한 가지로 채운다(gold 검증이 빈칸을 거부하기 때문).
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

from app.evaluation.gold import COLUMNS, EXTRA_COLUMNS, split_ids

STYLE = "사례"
OUT_COLUMNS = COLUMNS + EXTRA_COLUMNS
CATALOG = Path(__file__).resolve().parents[2] / "docs/LCA/data/lci-db-list-ecosq-849.csv"

# 엄격(S) 정답 기준(E1b, 2026-10-19 사용자 결정): 같은 이름(name_ko·category 가 글자 그대로 같음)의 데이터셋이 여럿이면
# year 가 가장 큰 판만 S 에 두고 구판은 A 에만. 최고 연도가 둘 이상(기관만 다름)이면 고르지 않고 그대로 두며 보고한다.
NORMALIZE_NOTE = "정규화: 동명 최신 판만 S (2026-10-19 사용자 결정)"
# 글자는 다르지만 같은 물질인 쌍(띄어쓰기·약칭 괄호만 다름). 사유: name_en·약칭이 같고 표기·연도만 다르다(사용자 확인).
# 합금·등급·제법(NCC·PDH) 변형은 넣지 않는다. 새 쌍은 여기 추가하지 말고 보고한다.
SAME_SUBSTANCE = {
    "list-66": "list-801",  # High-Density Polyethylene, HDPE (2000) = High-density polyethylene(HDPE) (2024)
    "list-74": "list-815",  # Methyl methacrylate, MMA (2002) = Methyl methacrylate(MMA) (2024)
    "list-75": "list-838",  # styrene acrylonitrile, SAN (2002) = Styrene acrylonitrile(SAN) (2024)
    "list-51": "list-897",  # polyethylene terephthalate, PET (2003) = Polyethylene terephthalate(PET) (2024)
}


def load_catalog(path=CATALOG):
    """{list-N: (name_ko, category, year)}."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {f"list-{r['lci_database_sn']}": (r["name_ko"], r["category"], int(r["year"])) for r in csv.DictReader(f)}


def name_key(d, catalog):
    d = SAME_SUBSTANCE.get(d, d)
    return catalog[d][:2]


def latest_of(catalog):
    """{같은 이름 키: 최신 id 또는 None(최고 연도 동률)}. 판이 하나뿐인 이름은 넣지 않는다."""
    groups = {}
    for d in catalog:
        groups.setdefault(name_key(d, catalog), []).append(d)
    out = {}
    for k, ids in groups.items():
        if len(ids) > 1:
            top = max(catalog[d][2] for d in ids)
            best = [d for d in ids if catalog[d][2] == top]
            out[k] = best[0] if len(best) == 1 else None
    return out


def normalize_latest(expected, a, s, catalog, latest=None):
    """(expected, a, s, 동률로 건너뛴 이름 목록). s 의 같은 이름 묶음마다 최신 하나만 남기고, 빠진 구판은 a 에 남긴다.
    a[0] 이 속한 이름이 바뀌면 최신 id 를 a 맨 앞으로, expected = a[0]. 이미 정규화된 입력엔 그대로(멱등)."""
    latest = latest_of(catalog) if latest is None else latest
    new_s, seen, ties, picked = [], set(), [], {}
    for d in s:
        k = name_key(d, catalog)
        if k not in latest:
            new_s.append(d)
        elif latest[k] is None:
            new_s.append(d)
            if k not in ties:
                ties.append(k)
        elif k not in seen:
            seen.add(k)
            picked[k] = latest[k]
            new_s.append(latest[k])
    new_a = list(a)
    if picked and new_a and name_key(new_a[0], catalog) in picked:
        top = picked[name_key(new_a[0], catalog)]
        new_a = [top] + [d for d in new_a if d != top]
    new_a += [d for d in list(picked.values()) + list(s) if d not in new_a]  # S 에 든 최신 판과 S 에서 빠진 구판은 A 에 있어야 한다
    return (new_a[0] if new_a else expected), new_a, new_s, ties


def normalize_rows(rows, catalog):
    """계약 행 목록을 제자리에서 정규화. 반환: ([(행, 전, 후)], [(행, 동률 이름)]). 전·후 = (expected, a_accept, s_accept) 문자열."""
    latest, changed, ties = latest_of(catalog), [], []
    for r in rows:
        if r["label_type"] == "none":
            continue
        before = (r["expected_dataset_id"], r["a_accept"], r["s_accept"])
        e, a, s, t = normalize_latest(r["expected_dataset_id"], split_ids(r["a_accept"]), split_ids(r["s_accept"]), catalog, latest)
        ties += [(r, k) for k in t]
        after = (e, "|".join(a), "|".join(s))
        if after != before:
            r["expected_dataset_id"], r["a_accept"], r["s_accept"] = after
            changed.append((r, before, after))
    return changed, ties


def parse_flags(text):
    """(a_accept 또는 None, s_accept 또는 None, 해석 못 한 flag 목록). s_accept 가 [] 이면 'none' 으로 적힌 것."""
    a = s = None
    unknown = []
    for part in (p.strip() for p in (text or "").split(";")):
        if not part:
            continue
        m = re.fullmatch(r"([AS])_accept=(.+)", part)
        if m:
            ids = [] if m[2].strip() == "none" else [x.strip() for x in m[2].split(",") if x.strip()]
            if m[1] == "A":
                a = ids
            else:
                s = ids
        elif re.fullmatch(r"S\s+none", part):
            s = []
        else:
            unknown.append(part)
    return a, s, unknown


def convert(rows, source="case-v1"):
    """(계약 행 목록, {no: [해석 못 한 flag]})."""
    out, unknown = [], {}
    for r in rows:
        lt, label_id = r["label_type"].strip(), r["label_dataset_id"].strip()
        a, s, unk = parse_flags(r.get("flags", ""))
        if unk:
            unknown[r["no"]] = unk
        if lt == "none":
            a = s = []
        else:
            if a is None:
                a = [label_id]
            if s is None:
                s = [label_id] if lt == "exact" else []
        out.append({c: "" for c in OUT_COLUMNS} | {
            "bom_text": r["input_name"].strip(), "spec": r["input_spec"].strip(), "expected_dataset_id": "" if lt == "none" else label_id,
            "is_no_match": "1" if lt == "none" else "0", "input_style": STYLE, "label_source": "manual", "split": "dev",
            "source": source, "note": f"no={r['no']}; BOM {r['bom_rows']}; {r['status']}", "label_type": lt,
            "a_accept": "|".join(a), "s_accept": "|".join(s), "decided_by": r["decided_by"].strip()})
    return out, unknown


def print_changes(changed, ties, row_id):
    print(f"정규화(동명 최신 판만 S): 바뀐 행 {len(changed)}")
    for r, b, a in changed:
        print(f"  {row_id(r)} {r['bom_text']}: expected {b[0]} -> {a[0]} | a_accept {b[1]} -> {a[1]} | s_accept {b[2]} -> {a[2]}")
    for r, (name, cat) in ties:
        print(f"  동률(최고 연도 판이 둘 이상) 그대로 둠: {row_id(r)} {r['bom_text']} — {name} ({cat})")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="사례 세트 -> 정답셋 계약 CSV")
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default="case-v1", help="source 열 값(출력 파일 이름과 맞춘다)")
    args = ap.parse_args(argv)
    with open(args.src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out, unknown = convert(rows, args.source)
    changed, ties = normalize_rows(out, load_catalog())
    for r, _, _ in changed:
        r["decided_by"] = "user"  # 사용자 결정에 따른 정규화
        r["note"] = f"{r['note']}; {NORMALIZE_NOTE}"
    print_changes(changed, ties, lambda r: r["note"].split(";")[0])
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    n = Counter(r["label_type"] for r in out)
    print(f"{args.out}: {len(out)}행 (exact {n['exact']} / proxy {n['proxy']} / none {n['none']})")
    for no, flags in unknown.items():
        print(f"해석하지 않은 flag — no {no}: {'; '.join(flags)}")


if __name__ == "__main__":
    main()
