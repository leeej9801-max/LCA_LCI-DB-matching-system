"""신뢰도 규칙 후보 비교(E2). 순수 함수만. 앱의 규칙은 바꾸지 않고 결과만 본다.

행(row) 입력: rows.csv 와 같은 정보 — rank_tfidf, rank_dense, score_dense(그 케이스 1위 후보의 밀집 점수),
gap_dense(그 케이스 밀집 목록의 1위 점수 − 2위 점수), ok_A·ok_strict(1위가 맞았는가, 정답 없음 행은 0), is_none.
후보(각각 '높음'·'보통'·'낮음'):
  R0 앱 규칙(app.bom.match.confidence) · R1 R0 + '높음'은 score_dense ≥ τ 일 때만 · R2 R0 + '높음'은 gap_dense ≥ δ 일 때만 · R3 R1 과 R2 둘 다.
  조건을 못 넘은 '높음'은 '보통'으로 내린다(낮음은 그대로).
"""
import numpy as np

from app.bom.match import confidence

LEVELS = ("높음", "보통", "낮음")
# 격자는 결과를 보기 전에 정했다(dev 분할만 본다). score_dense 는 bge-m3 코사인(대개 0.4~0.9)
TAU_GRID = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
DELTA_GRID = (0.01, 0.02, 0.03, 0.05, 0.07, 0.10)
COMPLEXITY = {"R0": 0, "R1": 1, "R2": 1, "R3": 2}  # 같으면 단순한 것: R0 < R1 = R2 < R3
# 선택 기준(잠정, 2026-10-19): '높음' 비율 ≥ COVERAGE_MIN 인 후보 중 '높음' 오류율(A) 최소, 같으면 단순한 것, 그래도 같으면 비율 큰 것.
# 판정 규칙 고정(E2b, 측정 세트를 열기 전): 이름 세 개가 기준 상수이고 아래 별칭은 E2 코드 호환용이다
HIGH_RATIO_MIN = 0.45  # '높음' 비율 하한
HIGH_ERR_GOAL = 0.05  # 목표: '높음' 오류율(A) 95% 구간 상한이 이 값 이하일 때만 "5% 이하 달성"이라고 쓴다
HIGH_ERR_PASS = 0.10  # 합격: 비율 ≥ HIGH_RATIO_MIN 이고 오류율(A) 점추정 ≤ 이 값
COVERAGE_MIN, TARGET_ERROR, PASS_ERROR = HIGH_RATIO_MIN, HIGH_ERR_GOAL, HIGH_ERR_PASS
CURVE = (0.40, 0.35, 0.30)  # 45%에서 합격선을 못 넘으면 비율을 낮췄을 때의 곡선도 보고
SELECTION_RULE = (f"'높음' 비율 {COVERAGE_MIN:.0%} 이상인 후보 중 '높음' 오류율(A) 최소, 같으면 단순한 것(R0<R1=R2<R3), 그래도 같으면 비율 큰 것. "
                  f"참고 목표 {TARGET_ERROR:.0%}, 합격선 {PASS_ERROR:.0%}. 합격선을 못 넘으면 비율 {', '.join(f'{c:.0%}' for c in CURVE)} 곡선 함께 보고(잠정, 2026-10-19)")
BOOT_N, SEED = 1000, 42


def candidates():
    """[(이름, 규칙, 매개변수)] 미리 정한 격자 전체."""
    out = [("R0", "R0", {})]
    out += [(f"R1 τ={t:.2f}", "R1", {"tau": t}) for t in TAU_GRID]
    out += [(f"R2 δ={d:.2f}", "R2", {"delta": d}) for d in DELTA_GRID]
    out += [(f"R3 τ={t:.2f} δ={d:.2f}", "R3", {"tau": t, "delta": d}) for t in TAU_GRID for d in DELTA_GRID]
    return out


def judge(row, rule, params):
    """한 행의 등급. 1위 후보가 없으면(rank 둘 다 None 이고 score 도 없음) 앱 규칙대로 '낮음'."""
    level = confidence(row.get("rank_tfidf"), row.get("rank_dense"))
    if level != "높음" or rule == "R0":
        return level
    sd, gap = row.get("score_dense"), row.get("gap_dense")
    ok_tau = "tau" not in params or (sd is not None and sd >= params["tau"])
    ok_delta = "delta" not in params or (gap is not None and gap >= params["delta"])
    return "높음" if ok_tau and ok_delta else "보통"


def level_stats(rows, levels):
    """등급별 {rows, acc_A, acc_strict} + '높음' 오류율(A)·비율. 정답 없음 행은 그 등급의 오답(level_table 과 같은 규칙)."""
    out = {}
    for lv in LEVELS:
        rs = [r for r, x in zip(rows, levels) if x == lv]
        out[lv] = {"rows": len(rs), "acc_A": sum(r["ok_A"] for r in rs) / len(rs) if rs else None,
                   "acc_strict": sum(r["ok_strict"] for r in rs) / len(rs) if rs else None}
    high = out["높음"]
    return {"levels": out, "high_error_A": None if high["acc_A"] is None else 1 - high["acc_A"],
            "high_coverage": high["rows"] / len(rows) if rows else None}


def bootstrap_high(rows, levels_by_cand, n=BOOT_N, seed=SEED):
    """후보마다 '높음' 오류율(A)·비율의 95% 구간. 모든 후보가 같은 재표본(행 단위 복원추출)을 쓴다."""
    m = len(rows)
    if m == 0:
        return {}
    rng = np.random.default_rng(seed)
    weights = np.stack([np.bincount(rng.integers(0, m, m), minlength=m) for _ in range(n)])  # n × m 재표본 횟수
    wrong = np.array([1 - r["ok_A"] for r in rows], dtype=float)
    out = {}
    for name, levels in levels_by_cand.items():
        high = np.array([x == "높음" for x in levels], dtype=float)
        k = weights @ high
        err = np.divide(weights @ (high * wrong), k, out=np.full(n, np.nan), where=k > 0)
        cov = k / m
        err = err[~np.isnan(err)]
        out[name] = {"high_error_A": [float(np.percentile(err, 2.5)), float(np.percentile(err, 97.5))] if len(err) else [None, None],
                     "high_coverage": [float(np.percentile(cov, 2.5)), float(np.percentile(cov, 97.5))]}
    return out


def select(results, coverage_min=COVERAGE_MIN):
    """results: [{name, rule, high_error_A, high_coverage}]. 기준을 만족하는 후보가 없으면 None."""
    ok = [r for r in results if r["high_coverage"] is not None and r["high_coverage"] >= coverage_min and r["high_error_A"] is not None]
    if not ok:
        return None
    return min(ok, key=lambda r: (round(r["high_error_A"], 12), COMPLEXITY[r["rule"]], -r["high_coverage"]))["name"]


def verdict(t):
    """후보 하나의 판정(E2b). pass_point = 비율 ≥ HIGH_RATIO_MIN 이고 오류율(A) 점추정 ≤ HIGH_ERR_PASS,
    goal_guarantee = 오류율(A) 95% 구간 상한 ≤ HIGH_ERR_GOAL(구간이 없거나 '높음'이 없으면 False)."""
    cov, err = t["high_coverage"], t["high_error_A"]
    upper = (t.get("ci") or {}).get("high_error_A", [None, None])[1]
    return {"pass_point": bool(cov is not None and err is not None and cov >= HIGH_RATIO_MIN and err <= HIGH_ERR_PASS),
            "goal_guarantee": bool(upper is not None and upper <= HIGH_ERR_GOAL), "ci_upper": upper}


def verdict_lines(t):
    """리포트 문구. '5% 이하 달성' 같은 문구는 goal_guarantee 가 참일 때만 쓴다. 구간은 항상 병기."""
    v = verdict(t)
    ci = (t.get("ci") or {}).get("high_error_A", [None, None])
    span = "—" if ci[0] is None else f"{ci[0]:.1%}~{ci[1]:.1%}"
    err = "—" if t["high_error_A"] is None else f"{t['high_error_A']:.1%}"
    cov = "—" if t["high_coverage"] is None else f"{t['high_coverage']:.1%}"
    lines = [f"- ① 합격(점추정): {'예' if v['pass_point'] else '아니오'} — '높음' 비율 {cov}(기준 {HIGH_RATIO_MIN:.0%} 이상)·오류율(A) {err}(기준 {HIGH_ERR_PASS:.0%} 이하), 오류율 95% 구간 {span}",
             f"- ② 목표 {HIGH_ERR_GOAL:.0%} 보증(구간 상한 ≤ {HIGH_ERR_GOAL:.0%}): {'예' if v['goal_guarantee'] else '아니오'}"]
    lines.append(f"- '높음' 오류율 {HIGH_ERR_GOAL:.0%} 이하 달성(구간 상한 {v['ci_upper']:.1%})" if v["goal_guarantee"]
                 else f"- {HIGH_ERR_GOAL:.0%} 목표는 보증하지 못함(점추정이 낮아도 구간 상한이 넘는다)")
    return lines


def compare(rows, with_ci=True):
    """한 케이스의 후보 비교 표. {candidates: [...], selected, passed, curve}."""
    table, levels_by = [], {}
    for name, rule, params in candidates():
        levels = [judge(r, rule, params) for r in rows]
        levels_by[name] = levels
        table.append({"name": name, "rule": rule, "params": params, **level_stats(rows, levels)})
    ci = bootstrap_high(rows, levels_by) if with_ci else {}
    for t in table:
        t["ci"] = ci.get(t["name"])
    chosen = select(table)
    best = next((t for t in table if t["name"] == chosen), None)
    passed = bool(best and best["high_error_A"] <= PASS_ERROR)
    curve = None if passed else {f"{c:.2f}": select(table, c) for c in CURVE}
    return {"rule": SELECTION_RULE, "candidates": table, "selected": chosen, "passed": passed, "curve": curve}
