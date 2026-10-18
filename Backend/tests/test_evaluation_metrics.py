"""평가 지표 시험(DB 없음). 기대값은 손으로 계산했다."""
import pytest

from app.evaluation import metrics as m

NAMES = {"A": "알루미늄", "A2": "알루미늄", "B": "냉연강판", "C": "열연강판", "D": "경유"}


def row(expected, ranking, **kw):
    return {"expected": expected, "expected_name": NAMES.get(expected), "ranking": [(d, s) for d, s in ranking], "names": NAMES, **kw}


ROWS = [
    row("A", [("A", 0.9), ("B", 0.5), ("C", 0.1)]),   # strict 1
    row("B", [("A", 0.8), ("C", 0.4), ("B", 0.3)]),   # strict 3
    row("C", [("A", 0.7), ("D", 0.2)]),               # 상위에 없음
    row(None, [("A", 0.95)]),                         # 정답 없음
]


def test_strict_metrics_by_hand():
    s = m.summarize(ROWS, "strict")  # 정답 있는 3행만
    assert s["top1"] == pytest.approx(1 / 3)
    assert s["top3"] == pytest.approx(2 / 3)
    assert s["recall@5"] == pytest.approx(2 / 3) and s["recall@10"] == pytest.approx(2 / 3)
    assert s["mrr"] == pytest.approx((1 + 1 / 3 + 0) / 3)


def test_name_level_differs_from_strict():
    r = row("A2", [("A", 0.9), ("A2", 0.8), ("B", 0.1)])  # 1위 A 는 A2 와 이름이 같다
    assert m.rank_strict(r) == 2 and m.rank_name(r) == 1
    r2 = row("B", [("A", 0.9), ("A2", 0.8), ("B", 0.1)])  # 동명 A·A2 를 접으면 B 는 2위
    assert m.rank_strict(r2) == 3 and m.rank_name(r2) == 2
    assert m.summarize([r, r2], "strict")["top1"] == 0.0
    assert m.summarize([r, r2], "name")["top1"] == pytest.approx(0.5)
    assert m.summarize([r, r2], "name")["mrr"] == pytest.approx((1 + 1 / 2) / 2)


def test_no_answer_rows_only_gives_none():
    assert m.summarize([row(None, [("A", 1.0)])]) == {k: None for k in m.KEYS}


def test_coverage_accuracy_by_hand():
    # 1위 점수 순: 정답없음(0.95, 오답) → r1(0.9, 정답) → r2(0.8, 오답) → r3(0.7, 오답)
    cov = {x["coverage"]: x for x in m.coverage_accuracy(ROWS)}
    assert cov[100]["accepted"] == 4 and cov[100]["accuracy_strict"] == pytest.approx(1 / 4) and cov[100]["errors_strict"] == 3
    assert cov[60]["accepted"] == 3 and cov[60]["accuracy_strict"] == pytest.approx(1 / 3)  # ceil(4*0.6)=3
    assert cov[40]["accepted"] == 2 and cov[40]["accuracy_strict"] == pytest.approx(1 / 2)
    assert cov[20]["accepted"] == 1 and cov[20]["accuracy_strict"] == 0.0 and cov[20]["min_score"] == 0.95  # 정답 없음 행을 받아들임 = 오답


def test_bootstrap_is_deterministic_and_paired():
    other = [row("A", [("B", 0.9), ("A", 0.5)]), *ROWS[1:]]  # 첫 행만 1위를 놓친 케이스
    a = m.bootstrap({"X": ROWS, "Y": other}, n=200, seed=42)
    b = m.bootstrap({"X": ROWS, "Y": other}, n=200, seed=42)
    assert a == b
    lo, hi = a["cases"]["X"]["top1"]
    assert 0.0 <= lo <= 1 / 3 <= hi <= 1.0
    dlo, dhi = a["diff"]["Y-X"]["top1"]
    assert dlo <= dhi <= 0.0  # 같은 재표본: Y 는 X 보다 절대 낫지 않다
    assert m.bootstrap({"X": ROWS, "Y": ROWS}, n=100, seed=42)["diff"]["Y-X"]["mrr"] == [0.0, 0.0]


def test_slices_mark_small_samples():
    rows = [dict(r, input_style="약어" if i < 2 else "영문", hard_pair_group="g1" if i == 0 else "", label_source="pool", category="금속")
            for i, r in enumerate(ROWS)]
    s = m.slices(rows)
    assert s["input_style"]["약어"]["n"] == 2 and s["input_style"]["약어"]["small"] is True
    assert s["hard_pair_group"]["있음"]["n"] == 1 and s["hard_pair_group"]["없음"]["n"] == 3
    assert s["input_style"]["약어"]["top1"] == pytest.approx(0.5)
