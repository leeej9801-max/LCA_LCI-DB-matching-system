"""평가 지표. 순수 함수만(DB·네트워크 없음).

행(row) 형식: {"expected": dataset_id | None(정답 없음), "expected_name": name_ko | None,
              "ranking": [(dataset_id, score), ...](점수 순), "names": {dataset_id: name_ko},
              조각용 "input_style", "hard_pair_group", "label_source", "category"}
strict = dataset_id 일치, name = 국문명 일치(동명 중복을 접은 순위).
F3: "A" = row["a_accept"] 안의 id 중 가장 앞 순위, "S" = row["s_accept"] 안의 id 중 가장 앞 순위.
    두 키가 없거나 None 이면 옛 정답셋 → [expected] 로 본다. s_accept 가 빈 목록이면 그 행은 S 의 분모에서 뺀다.
"""
import math
import random
from itertools import combinations

KEYS = ("top1", "top3", "recall@5", "recall@10", "mrr")
LEVELS = ("strict", "name", "A", "S")
COVERAGE = (100, 80, 60, 40, 20)
SMALL = 10  # 조각 표본(정답 있는 행)이 이보다 적으면 "표본 적음" (E2: 5 → 10)


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


def accept_ids(row, level):
    """A·S 수준에서 맞다고 보는 id 목록(정답 없음 행은 빈 목록)."""
    if row["expected"] is None:
        return []
    got = row.get("a_accept" if level == "A" else "s_accept")
    return [row["expected"]] if got is None else list(got)


def rank_accept(row, level):
    ok = set(accept_ids(row, level))
    for i, (d, _) in enumerate(row["ranking"], 1):
        if d in ok:
            return i
    return None


def applicable(row, level):
    """이 수준의 분모에 드는 행인가. 정답 없음 행은 순위 지표에서 빠지고, S 는 s_accept 가 빈 행도 빠진다."""
    if row["expected"] is None:
        return False
    return bool(accept_ids(row, level)) if level in ("A", "S") else True


def ranks(row, level):
    if level == "strict":
        return rank_strict(row)
    return rank_accept(row, level) if level in ("A", "S") else rank_name(row)


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
    answerable = [r for r in rows if applicable(r, level)]
    if not answerable:
        return {k: None for k in KEYS}
    scores = [row_scores(ranks(r, level)) for r in answerable]
    return {k: sum(s[k] for s in scores) / len(scores) for k in KEYS}


def top1_ok(row, level="strict"):
    """받아들였을 때 맞았는가. 정답 없음 행은 시스템이 늘 후보를 내므로 언제나 오답."""
    return applicable(row, level) and ranks(row, level) == 1


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
        ans = [r for r in rows_by_case[c] if applicable(r, level)]
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
        "hard_pair_value": lambda r: r.get("hard_pair_group") or "없음",  # E2: 그룹별('공정명만' 등)
        "expected_role": lambda r: r.get("expected_role") or ("정답 없음" if r["expected"] is None else "—"),
        "label_source": lambda r: r.get("label_source") or "—",
        "category": lambda r: r.get("category") or ("정답 없음" if r["expected"] is None else "—"),
        "label_type": lambda r: r.get("label_type") or "—",
        "product": lambda r: r.get("product") or "—",
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
                                "top1_A": summarize(rs, "A")["top1"], "top1_S": summarize(rs, "S")["top1"], "small": answerable < SMALL}
    return out


def says_no_answer(c0, c1, c2, confidence, no_answer_confidence="낮음"):
    """앱과 같은 판정: C2 1위 후보의 두 목록 순위(C0·C1 순위에서 위치 조회)를 confidence 에 넣어 '낮음'이면 no_answer. 후보가 없어도 no_answer.
    confidence 함수와 기준 값은 app.bom.match 의 것을 넘겨 받는다(규칙을 여기서 다시 쓰지 않는다)."""
    if not c2:
        return True
    top = c2[0][0]
    pos = lambda ranking: next((i for i, (d, _) in enumerate(ranking, 1) if d == top), None)  # noqa: E731
    return confidence(pos(c0), pos(c1)) == no_answer_confidence


def top1_level(c0, c1, c2, confidence):
    """C2 1위 후보의 신뢰도 등급(앱과 같은 confidence 함수). 후보가 없으면 None."""
    if not c2:
        return None
    top = c2[0][0]
    pos = lambda ranking: next((i for i, (d, _) in enumerate(ranking, 1) if d == top), None)  # noqa: E731
    return confidence(pos(c0), pos(c1))


def row_detail(row, c0, c1, confidence):
    """errors.csv·rows.csv 의 행별 열(E1). 이 케이스 1위 후보의 신뢰도 등급(top1_level)과 C0·C1 순위, C1 점수, 정답의 strict 순위.
    c0·c1 이 None(그 케이스를 돌리지 않음)이면 순위·점수·등급은 None."""
    top = row["ranking"][0][0] if row["ranking"] else None
    hit = lambda ranking: next(((i, s) for i, (d, s) in enumerate(ranking, 1) if d == top), (None, None)) if ranking is not None and top else (None, None)  # noqa: E731
    (rank_tfidf, _), (rank_dense, score_dense) = hit(c0), hit(c1)
    level = top1_level(c0, c1, row["ranking"], confidence) if c0 is not None and c1 is not None else None
    return {"confidence": level, "rank_tfidf": rank_tfidf, "rank_dense": rank_dense, "score_dense": score_dense, "gold_rank": rank_strict(row)}


RECALL_KS = (1, 3, 10, 30)


def recall_at(rows, level, ks=RECALL_KS, miss_k=30):
    """정답이 상위 K 안에 있는 비율(E2b). level A·S, 정답 없음(none) 행과 그 수준의 분모 밖 행은 제외.
    miss_ids: 상위 miss_k 안에 정답이 없는 행의 label_id(재순위가 올릴 수 없는 행). 분모가 0 이면 값은 None."""
    ans = [r for r in rows if applicable(r, level)]
    rk = [ranks(r, level) for r in ans]
    out = {"n": len(ans), **{f"top{k}": (sum(x is not None and x <= k for x in rk) / len(ans) if ans else None) for k in ks}}
    out["miss_ids"] = [r["label_id"] for r, x in zip(ans, rk) if x is None or x > miss_k]
    out["miss_k"] = miss_k
    return out


def rank_worse(before, after, level="A"):
    """Veto 로 정답 순위가 나빠졌는가(E2b): 전 순위가 있고, 후 순위가 더 크거나 없어졌다. 정답 없음 행은 False."""
    b, a = rank_accept(before, level), rank_accept(after, level)
    return b is not None and (a is None or a > b)


def dense_gap(dense):
    """밀집 목록의 1위 점수 − 2위 점수(E2 R2 규칙 입력). 후보가 둘 미만이면 None."""
    return dense[0][1] - dense[1][1] if dense and len(dense) >= 2 else None


CONF_LEVELS = ("높음", "보통", "낮음")


def level_table(rows, levels):
    """신뢰도 등급별 1위 정답률. levels[i] = rows[i] 의 1위 등급. 정답 없음(none) 행은 그 등급의 오답으로 센다
    (그 등급으로 후보를 보여 주면 사용자는 틀린 후보를 보게 되므로). 분모가 0 이면 None."""
    out = {}
    for lv in CONF_LEVELS:
        rs = [r for r, x in zip(rows, levels) if x == lv]
        ok_a = sum(1 for r in rs if r["expected"] is not None and top1_ok(r, "A"))
        ok_s = sum(1 for r in rs if r["expected"] is not None and top1_ok(r, "strict"))
        out[lv] = {"rows": len(rs), "none_rows": sum(1 for r in rs if r["expected"] is None),
                   "ok_A": ok_a, "acc_A": ok_a / len(rs) if rs else None,
                   "ok_strict": ok_s, "acc_strict": ok_s / len(rs) if rs else None}
    return out


def no_answer_table(rows, flags):
    """none 행(expected 없음)과 정답 있음 행을 no_answer 여부로 센 표. flags[i] = rows[i] 에 대해 no_answer 로 답했는가.
    정거부율 = none 행 중 no_answer 비율, 오거부율 = 정답 있음 행 중 no_answer 비율. 분모가 0 이면 None."""
    none = [f for r, f in zip(rows, flags) if r["expected"] is None]
    ans = [f for r, f in zip(rows, flags) if r["expected"] is not None]
    return {"none": {"rows": len(none), "no_answer": sum(none), "candidate": len(none) - sum(none)},
            "answerable": {"rows": len(ans), "no_answer": sum(ans), "candidate": len(ans) - sum(ans)},
            "correct_reject_rate": sum(none) / len(none) if none else None,
            "false_reject_rate": sum(ans) / len(ans) if ans else None}


SYNTHETIC_RATIO = 0.5
SYNTHETIC_WARNING = "정답·입력 상당수가 작성자=판정자인 합성 데이터. 실무 성능이 아님."
REVIEW_WARNING = "라벨 사람 검수 전 — decided_by 에 user 가 하나도 없다. 이 숫자는 사람이 확인한 정답 기준이 아니다."


def gold_header(labels):
    """report.md 맨 위 줄용: 행 수·label_type 개수·decided_by 분포와, 사람 검수가 없을 때의 경고(없으면 None)."""
    types, by = {}, {}
    for lab in labels:
        t = lab.get("label_type") or "미지정"
        types[t] = types.get(t, 0) + 1
        who = lab.get("decided_by") or "미기재"
        by[who] = by.get(who, 0) + 1
    has_user = any("user" in who.split("+") for who in by)
    claude_ratio = by.get("claude", 0) / len(labels) if labels else 0.0  # 순수 claude 판정(user+claude 는 사람이 본 것이라 뺀다)
    return {"rows": len(labels), "label_types": types, "decided_by": by, "has_user": has_user,
            "warning": None if has_user else REVIEW_WARNING, "claude_ratio": claude_ratio,
            "synthetic_warning": SYNTHETIC_WARNING if claude_ratio > SYNTHETIC_RATIO else None}
