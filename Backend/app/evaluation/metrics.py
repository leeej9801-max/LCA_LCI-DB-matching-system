"""평가 지표. 순수 함수만(DB·네트워크 없음).

행(row) 형식: {"expected": dataset_id | None(정답 없음), "expected_name": name_ko | None,
              "ranking": [(dataset_id, score), ...](점수 순), "names": {dataset_id: name_ko},
              조각용 "input_style", "hard_pair_group", "label_source", "category"}
strict = dataset_id 일치, name = 국문명 일치(동명 중복을 접은 순위).
"""
import math
import random
from itertools import combinations

KEYS = ("top1", "top3", "recall@5", "recall@10", "mrr")
LEVELS = ("strict", "name")
COVERAGE = (100, 80, 60, 40, 20)
SMALL = 5  # 조각 표본이 이보다 적으면 "표본 적음"


def rank_strict(row):
    ids = [d for d, _ in row["ranking"]]
    return ids.index(row["expected"]) + 1 if row["expected"] in ids else None


def rank_name(row):
    """국문명이 같은 후보를 하나로 접은 목록에서 정답 이름의 순위."""
    if row["expected"] is None:
        return None
    target = row["expected_name"]
    folded = []
    for d, _ in row["ranking"]:
        name = row["names"].get(d)
        if name not in folded:
            folded.append(name)
    return folded.index(target) + 1 if target in folded else None


def ranks(row, level):
    return rank_strict(row) if level == "strict" else rank_name(row)


def row_scores(rank):
    """정답 있는 행 하나의 지표 값(정답이 상위 목록에 없으면 rank=None → 모두 0)."""
    return {
        "top1": float(rank == 1),
        "top3": float(rank is not None and rank <= 3),
        "recall@5": float(rank is not None and rank <= 5),
        "recall@10": float(rank is not None and rank <= 10),
        "mrr": 1.0 / rank if rank else 0.0,
    }


def summarize(rows, level="strict"):
    """정답 있는 행의 평균. 정답 있는 행이 없으면 값은 None(0으로 채우지 않는다)."""
    answerable = [r for r in rows if r["expected"] is not None]
    if not answerable:
        return {k: None for k in KEYS}
    scores = [row_scores(ranks(r, level)) for r in answerable]
    return {k: sum(s[k] for s in scores) / len(scores) for k in KEYS}


def top1_ok(row, level="strict"):
    """받아들였을 때 맞았는가. 정답 없음 행은 시스템이 늘 후보를 내므로 언제나 오답."""
    return row["expected"] is not None and ranks(row, level) == 1


def coverage_accuracy(rows, levels=COVERAGE):
    """1위 점수 내림차순으로 상위 p%만 받아들였을 때의 정확도와 오답 수. 정답 없음 행은 받아들이면 오답."""
    ordered = sorted(rows, key=lambda r: -(r["ranking"][0][1] if r["ranking"] else -math.inf))
    out = []
    for p in levels:
        k = max(1, math.ceil(len(ordered) * p / 100)) if ordered else 0
        accepted = ordered[:k]
        strict = sum(top1_ok(r, "strict") for r in accepted)
        name = sum(top1_ok(r, "name") for r in accepted)
        out.append({"coverage": p, "accepted": k,
                    "accuracy_strict": strict / k if k else None, "errors_strict": k - strict,
                    "accuracy_name": name / k if k else None, "errors_name": k - name,
                    "min_score": accepted[-1]["ranking"][0][1] if accepted and accepted[-1]["ranking"] else None})
    return out


def percentile(sorted_values, q):
    """선형 보간 백분위(0~100)."""
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def bootstrap(rows_by_case, n=1000, seed=42, keys=("top1", "top3", "mrr"), level="strict"):
    """행 단위 복원추출 95% 구간. 모든 케이스가 같은 재표본을 쓰므로 케이스 쌍의 차이도 대응 비교가 된다.
    rows_by_case: {case: [row, ...]} — 케이스마다 같은 행이 같은 순서로 들어 있어야 한다. 정답 있는 행만 쓴다."""
    cases = list(rows_by_case)
    values = {}
    for c in cases:
        ans = [r for r in rows_by_case[c] if r["expected"] is not None]
        values[c] = [row_scores(ranks(r, level)) for r in ans]
    m = len(values[cases[0]]) if cases else 0
    if m == 0:
        return {"n": n, "seed": seed, "level": level, "cases": {}, "diff": {}}
    rng = random.Random(seed)
    samples = [[rng.randrange(m) for _ in range(m)] for _ in range(n)]
    stats = {c: {k: [sum(values[c][i][k] for i in s) / m for s in samples] for k in keys} for c in cases}
    result = {"n": n, "seed": seed, "level": level, "rows": m, "cases": {}, "diff": {}}
    for c in cases:
        result["cases"][c] = {k: [percentile(sorted(stats[c][k]), 2.5), percentile(sorted(stats[c][k]), 97.5)] for k in keys}
    for a, b in combinations(cases, 2):
        result["diff"][f"{b}-{a}"] = {
            k: [percentile(sorted(y - x for x, y in zip(stats[a][k], stats[b][k])), q) for q in (2.5, 97.5)] for k in keys}
    return result


def slices(rows):
    """조각별 strict 지표. 조각 이름 → {값: {n, answerable, top1, top3, mrr, small}}."""
    groups = {
        "input_style": lambda r: r.get("input_style") or "—",
        "hard_pair_group": lambda r: "있음" if r.get("hard_pair_group") else "없음",
        "label_source": lambda r: r.get("label_source") or "—",
        "category": lambda r: r.get("category") or ("정답 없음" if r["expected"] is None else "—"),
    }
    out = {}
    for name, key in groups.items():
        buckets = {}
        for r in rows:
            buckets.setdefault(key(r), []).append(r)
        out[name] = {}
        for value, rs in sorted(buckets.items()):
            s = summarize(rs, "strict")
            answerable = sum(r["expected"] is not None for r in rs)
            out[name][value] = {"n": len(rs), "answerable": answerable, "top1": s["top1"], "top3": s["top3"], "mrr": s["mrr"],
                                "small": answerable < SMALL}
    return out
