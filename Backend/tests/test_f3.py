"""F3: 평가 계약 확장(label_type·a_accept·s_accept)과 A/S 지표, none 판정. DB 없는 시험 + (DB가 있으면) 적재 시험."""
import csv
from pathlib import Path

import psycopg
import pytest

from app.bom.match import confidence
from app.evaluation import metrics as m
from app.evaluation.gold import COLUMNS, EXTRA_COLUMNS, contract_values, read_csv, validate
from app.evaluation.run import report_md
from test_evaluation_gold import evaldb  # noqa: F401  (fixture 재사용)
from test_migrate import tempdb  # noqa: F401  (evaldb 가 쓰는 fixture)
from test_migrate import needs_db  # noqa: F401
from tools.case_to_gold import convert, parse_flags

ROOT = Path(__file__).resolve().parents[2]
KNOWN = {"list-1", "list-2", "list-3", "list-4"}
NAMES = {"A": "가", "B": "나", "C": "다", "D": "라"}


def row(expected, ranking, a=None, s=None, **kw):
    r = {"expected": expected, "expected_name": NAMES.get(expected), "ranking": [(d, 1.0) for d in ranking], "names": NAMES, **kw}
    if a is not None:
        r["a_accept"] = a
    if s is not None:
        r["s_accept"] = s
    return r


# ---------- A/S 판정 ----------
def test_a_s_levels_by_hand():
    r = row("A", ["B", "C", "A"], a=["A", "C"], s=["A"])  # strict 3위, A 는 C 가 2위, S 는 A 가 3위
    assert (m.rank_strict(r), m.rank_accept(r, "A"), m.rank_accept(r, "S")) == (3, 2, 3)
    r2 = row("A", ["C", "A"], a=["A", "C"], s=["A"])
    assert m.top1_ok(r2, "A") and not m.top1_ok(r2, "S") and not m.top1_ok(r2)
    r3 = row("A", ["D", "B"], a=["A"], s=["A"])
    assert m.rank_accept(r3, "A") is None and m.rank_accept(r3, "S") is None


def test_empty_s_accept_leaves_the_s_denominator():
    exact = row("A", ["A"], a=["A"], s=["A"])
    proxy = row("B", ["C"], a=["B"], s=[])  # 엄격 기준으로 맞는 것이 없음
    none = row(None, ["A"])
    assert m.applicable(proxy, "A") and not m.applicable(proxy, "S") and not m.applicable(none, "A")
    s = m.summarize([exact, proxy, none], "S")
    assert s["top1"] == 1.0 and s["mrr"] == 1.0  # 분모는 exact 한 행
    assert m.summarize([exact, proxy, none], "A")["top1"] == 0.5  # 분모 둘
    assert m.summarize([proxy], "S") == {k: None for k in m.KEYS}  # 분모 0 이면 None


def test_old_rows_without_accept_keys_mean_single_answer():
    old = row("A", ["B", "A"])
    assert m.rank_accept(old, "A") == 2 and m.rank_accept(old, "S") == 2 and m.applicable(old, "S")


def test_bootstrap_uses_level_denominator():
    rows = [row("A", ["A"], a=["A"], s=["A"]), row("B", ["C"], a=["B"], s=[])]
    assert m.bootstrap({"X": rows}, n=20, level="S")["rows"] == 1
    assert m.bootstrap({"X": rows}, n=20, level="A")["rows"] == 2


def test_slices_add_label_type_and_product():
    rows = [row("A", ["A"], label_type="exact", product="p1"), row(None, ["A"], label_type="none", product="p1"),
            row("B", ["B"], label_type="proxy", product="p2")]
    sl = m.slices(rows)
    assert set(sl["label_type"]) == {"exact", "proxy", "none"} and set(sl["product"]) == {"p1", "p2"}
    assert sl["label_type"]["none"]["answerable"] == 0 and sl["label_type"]["exact"]["top1_A"] == 1.0


# ---------- none 판정 (confidence 는 앱 것을 import, 입력별 기대값은 현재 규칙 기준) ----------
def test_says_no_answer_follows_confidence_argument():
    c0, c1, c2 = [("A", 1)], [("A", 1)], [("A", 1)]
    assert m.says_no_answer(c0, c1, c2, lambda t, d: "높음") is False
    seen = []
    assert m.says_no_answer([("B", 1), ("A", 1)], [("A", 1)], c2, lambda t, d: seen.append((t, d)) or "낮음") is True
    assert seen == [(2, 1)]  # 1위 후보 A 의 C0 순위 2, C1 순위 1
    assert m.says_no_answer([("B", 1)], [("A", 1)], c2, lambda t, d: seen.append((t, d)) or "보통") is False
    assert seen[-1] == (None, 1)  # 한쪽 목록에 없으면 None
    assert m.says_no_answer([], [], [], lambda t, d: "높음") is True  # 후보가 없으면 no_answer


def test_says_no_answer_with_the_app_confidence():
    both_first = [("A", 1)]
    assert m.says_no_answer(both_first, both_first, both_first, confidence) is False
    assert m.says_no_answer([("B", 1)] * 1, [("B", 1)], [("A", 1)], confidence) is True  # 1위 후보가 두 목록 어디에도 없음


def test_no_answer_table_counts_and_rates():
    rows = [row(None, ["A"]), row(None, ["A"]), row("A", ["A"]), row("B", ["C"]), row("C", ["C"])]
    t = m.no_answer_table(rows, [True, False, False, True, False])
    assert t["none"] == {"rows": 2, "no_answer": 1, "candidate": 1}
    assert t["answerable"] == {"rows": 3, "no_answer": 1, "candidate": 2}
    assert t["correct_reject_rate"] == 0.5 and t["false_reject_rate"] == pytest.approx(1 / 3)
    assert m.no_answer_table([row("A", ["A"])], [False])["correct_reject_rate"] is None  # none 행이 없으면 None


# ---------- 경고 줄 ----------
def test_gold_header_warns_only_without_user():
    claude = [{"label_type": "exact", "decided_by": "claude"}, {"label_type": "none", "decided_by": "claude"}]
    h = m.gold_header(claude)
    assert h["label_types"] == {"exact": 1, "none": 1} and h["decided_by"] == {"claude": 2} and h["warning"]
    assert m.gold_header(claude + [{"label_type": "proxy", "decided_by": "user"}])["warning"] is None
    assert m.gold_header([{"label_type": None, "decided_by": "user+claude"}])["warning"] is None


def _report(warning):
    case = {"label": "x", "state": "measured", **{lv: {k: 0.5 for k in m.KEYS} for lv in m.LEVELS}}
    return {"config": {"smoke": False, "group": "g", "gold_id": "gold-x", "split": "dev", "test_opened": False, "head_case": "C2"},
            "gold_stats": {"total": 3, "answerable": 2, "no_answer": 1, "gold_name": "x", "s_applicable": 1, "label_types": {"exact": 2, "none": 1},
                           "decided_by": {"claude": 3}, "warning": warning},
            "model_versions": {"embed_model": "e", "ollama_digest": "d", "ollama_digest_error": None, "index_version_id": "v", "index_hash": "0" * 64,
                               "tfidf": {}, "rrf_k": 60, "seed": 42, "git_sha": None, "python": "3", "scikit-learn": "1"},
            "meta": {"elapsed_s": 1}, "cases": {"C2": case}, "ci": None, "ci_levels": None, "slices": {}, "coverage_accuracy": {}, "errors": [],
            "no_answer_judgement": {"case": "C2", "rule": "r", "none": {"rows": 1, "no_answer": 1, "candidate": 0},
                                    "answerable": {"rows": 2, "no_answer": 0, "candidate": 2}, "correct_reject_rate": 1.0, "false_reject_rate": 0.0}}


def test_report_md_top_line_and_warning():
    md = report_md(_report(m.REVIEW_WARNING))
    first = md.splitlines()[0]
    assert "label_type exact 2 / none 1" in first and "decided_by claude 3" in first and "3행" in first
    assert "라벨 사람 검수 전" in md.splitlines()[1]
    assert "A 수준" in md and "S 수준" in md and "맞는 후보 없음 판정" in md and "정거부율" in md
    assert "라벨 사람 검수 전" not in report_md(_report(None))


# ---------- 계약 검증 ----------
def write(tmp_path, rows, extra=True, name="g.csv"):
    cols = COLUMNS + (EXTRA_COLUMNS if extra else [])
    p = tmp_path / name
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: "" for c in cols} | {"input_style": "s", "label_source": "manual", "is_no_match": "0"} | r)
    return p


def errs(tmp_path, rows, extra=True):
    _, header, parsed = read_csv(write(tmp_path, rows, extra))
    return validate(header, parsed, KNOWN)


def test_contract_valid_rows(tmp_path):
    assert errs(tmp_path, [
        {"bom_text": "a", "expected_dataset_id": "list-1", "label_type": "exact", "a_accept": "list-1|list-2", "s_accept": "list-1"},
        {"bom_text": "b", "expected_dataset_id": "list-3", "label_type": "proxy", "a_accept": "list-3", "s_accept": ""},  # proxy 는 s 가 비어도 정상
        {"bom_text": "c", "is_no_match": "1", "label_type": "none"},
        {"bom_text": "d", "expected_dataset_id": "list-4"},  # label_type 빈칸 = 옛 행
    ]) == []


def test_contract_errors(tmp_path):
    e = errs(tmp_path, [
        {"bom_text": "a", "expected_dataset_id": "list-1", "label_type": "exact", "a_accept": "list-1", "s_accept": ""},       # 2행: exact 인데 s 없음
        {"bom_text": "b", "is_no_match": "1", "label_type": "none", "a_accept": "list-1"},                                      # 3행: none 인데 a_accept
        {"bom_text": "c", "expected_dataset_id": "list-1", "label_type": "proxy", "a_accept": "list-1|list-99"},                # 4행: 없는 id
        {"bom_text": "d", "expected_dataset_id": "list-1", "label_type": "exact", "a_accept": "list-2", "s_accept": "list-2"},   # 5행: 첫 값 불일치
        {"bom_text": "e", "expected_dataset_id": "list-1", "label_type": "proxy", "a_accept": ""},                              # 6행: a_accept 없음
        {"bom_text": "f", "expected_dataset_id": "list-1", "label_type": "none"},                                               # 7행: none 인데 is_no_match=0
        {"bom_text": "g", "expected_dataset_id": "list-1", "label_type": "weird", "a_accept": "list-1"},                        # 8행: 값
        {"bom_text": "h", "expected_dataset_id": "list-1", "a_accept": "list-1"},                                               # 9행: label_type 없이 a_accept
    ])
    rows = sorted({n for n, _ in e})
    assert rows == [2, 3, 4, 5, 6, 7, 8, 9]
    assert any(n == 4 and "list-99" in msg for n, msg in e) and any(n == 2 and "s_accept" in msg for n, msg in e)


def test_old_csv_without_new_columns_passes(tmp_path):
    assert errs(tmp_path, [{"bom_text": "a", "expected_dataset_id": "list-1"}, {"bom_text": "b", "is_no_match": "1"}], extra=False) == []
    assert contract_values({"expected_dataset_id": "list-1"}) == (None, None, None, None)


def test_contract_values_for_db():
    assert contract_values({"label_type": "proxy", "a_accept": "list-1|list-2", "s_accept": "", "decided_by": "user"}) == ("proxy", ["list-1", "list-2"], [], "user")
    assert contract_values({"label_type": "none", "decided_by": "claude"}) == ("none", None, None, "claude")


# ---------- 사례 세트 변환 ----------
def test_parse_flags():
    assert parse_flags("A_accept=list-467,list-473;S_accept=none;missing=x,y") == (["list-467", "list-473"], [], ["missing=x,y"])
    assert parse_flags("S none;unit_회") == (None, [], ["unit_회"])
    assert parse_flags("") == (None, None, [])


def test_case_set_conversion_counts_and_validates():
    src = ROOT / "docs/LCA/data/gold-draft-2026-10-18.csv"
    with open(src, encoding="utf-8-sig", newline="") as f:
        out, unknown = convert(list(csv.DictReader(f)))
    assert [r["label_type"] for r in out].count("exact") == 8 and [r["label_type"] for r in out].count("proxy") == 5
    assert [r["label_type"] for r in out].count("none") == 1 and len(out) == 14
    by = {r["bom_text"]: r for r in out}
    assert by["고밀도 폴리에틸렌 HDPE"]["a_accept"] == "list-66|list-64|list-65" and by["고밀도 폴리에틸렌 HDPE"]["s_accept"] == "list-66"
    assert by["볼트 M6x20"]["s_accept"] == "" and by["프레스 가공"]["s_accept"] == ""
    assert set(unknown) == {"2", "6", "7", "9", "14"}


def list_ids():
    with open(ROOT / "docs/LCA/data/lci-db-list-ecosq-849.csv", encoding="utf-8-sig", newline="") as f:
        return {f"list-{r['lci_database_sn']}" for r in csv.DictReader(f)}


@pytest.mark.parametrize("rel", ["docs/LCA/data/gold/case-v1.csv", "docs/LCA/data/gold/measure-v1.csv"])
def test_real_gold_files_validate_against_the_list(rel):
    _, header, parsed = read_csv(ROOT / rel)
    assert validate(header, parsed, list_ids()) == []
    assert all(r["label_type"] in ("exact", "proxy", "none") for _, r in parsed)


@needs_db
def test_load_stores_new_columns(evaldb, tmp_path):  # noqa: F811
    from app.evaluation.gold import load
    p = write(tmp_path, [
        {"bom_text": "a", "expected_dataset_id": "list-1", "label_type": "exact", "a_accept": "list-1|list-2", "s_accept": "list-1", "decided_by": "user", "split": "dev"},
        {"bom_text": "b", "expected_dataset_id": "list-3", "label_type": "proxy", "a_accept": "list-3", "split": "dev"},
        {"bom_text": "c", "is_no_match": "1", "label_type": "none", "split": "dev"},
        {"bom_text": "d", "expected_dataset_id": "list-4", "split": "dev"}])
    gid, _ = load(evaldb, p, "f3", "v1")
    with psycopg.connect(evaldb) as conn:
        got = {t: r for t, *r in conn.execute("SELECT bom_text, label_type, a_accept, s_accept, decided_by FROM gold_label WHERE gold_id = %s", (gid,)).fetchall()}
    assert got["a"] == ["exact", ["list-1", "list-2"], ["list-1"], "user"] and got["b"] == ["proxy", ["list-3"], [], None]
    assert got["c"] == ["none", None, None, None] and got["d"] == [None, None, None, None]


def test_level_table_counts_none_rows_as_errors():
    rows = [
        {"expected": "list-1", "ranking": [("list-1", 1.0)], "a_accept": ["list-1"], "s_accept": ["list-1"], "label_type": "exact"},
        {"expected": "list-2", "ranking": [("list-9", 1.0)], "a_accept": ["list-2"], "s_accept": ["list-2"], "label_type": "exact"},
        {"expected": None, "ranking": [("list-3", 1.0)], "a_accept": None, "s_accept": None, "label_type": "none"},
    ]
    t = m.level_table(rows, ["높음", "높음", "보통"])
    assert t["높음"]["rows"] == 2 and t["높음"]["ok_A"] == 1 and t["높음"]["acc_A"] == 0.5
    assert t["보통"]["rows"] == 1 and t["보통"]["none_rows"] == 1 and t["보통"]["acc_A"] == 0
    assert t["낮음"]["rows"] == 0 and t["낮음"]["acc_A"] is None


def test_top1_level_uses_app_confidence():
    c0 = [("a", 1.0), ("b", 0.5)]
    c1 = [("a", 1.0)]
    assert m.top1_level(c0, c1, [("a", 1.0)], confidence) == "높음"
    assert m.top1_level(c0, c1, [("b", 1.0)], confidence) == "낮음"  # 밀집 목록에 없음 → 최대 낮음
    assert m.top1_level(c0, c1, [], confidence) is None


# E1b: 엄격(S) 정규화 — 동명은 최신 판만 S. 작은 가짜 목록으로 손계산
CAT = {
    "list-1": ("아연괴", "금속", 2003), "list-2": ("아연괴", "금속", 2007), "list-3": ("아연괴", "금속", 2022),  # 동명 3판
    "list-4": ("합금아연괴", "금속", 2022),  # 인접(이름 다름)
    "list-5": ("주석도금강판", "금속", 2005), "list-6": ("주석도금강판", "금속", 2005),  # 최고 연도 동률
    "list-66": ("고밀도 폴리에틸렌", "화학물질", 2000), "list-801": ("고밀도 폴리에틸렌(HDPE)", "화학물질", 2024),  # SAME_SUBSTANCE 쌍
}


def test_normalize_drops_old_editions_and_keeps_them_in_a():
    from tools.case_to_gold import normalize_latest
    assert normalize_latest("list-1", ["list-1", "list-4"], ["list-1", "list-2"], CAT) == ("list-3", ["list-3", "list-1", "list-4", "list-2"], ["list-3"], [])
    # 정답이 이미 최신이면 a 순서 유지, 빠진 구판만 a 끝에
    assert normalize_latest("list-3", ["list-3"], ["list-3", "list-1"], CAT) == ("list-3", ["list-3", "list-1"], ["list-3"], [])


def test_normalize_leaves_ties_and_neighbours_alone():
    from tools.case_to_gold import normalize_latest
    assert normalize_latest("list-5", ["list-5"], ["list-5"], CAT) == ("list-5", ["list-5"], ["list-5"], [("주석도금강판", "금속")])
    assert normalize_latest("list-4", ["list-4", "list-3"], ["list-4"], CAT) == ("list-4", ["list-4", "list-3"], ["list-4"], [])  # 인접은 그대로
    assert normalize_latest("list-9", ["list-9"], [], CAT)[2] == []  # proxy(s 없음)는 건드리지 않음


def test_normalize_same_substance_pair_and_is_idempotent():
    from tools.case_to_gold import normalize_latest
    once = normalize_latest("list-66", ["list-66", "list-64"], ["list-66"], CAT | {"list-64": ("파이프용 고밀도 폴리에틸렌", "화학물질", 2000)})
    assert once == ("list-801", ["list-801", "list-66", "list-64"], ["list-801"], [])
    cat = CAT | {"list-64": ("파이프용 고밀도 폴리에틸렌", "화학물질", 2000)}
    assert normalize_latest(*once[:3], cat) == once
    for e, a, s in (("list-1", ["list-1", "list-4"], ["list-1", "list-2"]), ("list-5", ["list-5"], ["list-5"])):
        first = normalize_latest(e, a, s, CAT)
        assert normalize_latest(*first[:3], CAT) == first


def test_normalize_rows_reports_changes_only():
    from tools.case_to_gold import normalize_rows
    rows = [{"bom_text": "a", "label_type": "exact", "expected_dataset_id": "list-1", "a_accept": "list-1", "s_accept": "list-1"},
            {"bom_text": "b", "label_type": "exact", "expected_dataset_id": "list-3", "a_accept": "list-3", "s_accept": "list-3"},
            {"bom_text": "c", "label_type": "none", "expected_dataset_id": "", "a_accept": "", "s_accept": ""}]
    changed, ties = normalize_rows(rows, CAT)
    assert [(r["bom_text"], b, a) for r, b, a in changed] == [("a", ("list-1", "list-1", "list-1"), ("list-3", "list-3|list-1", "list-3"))]
    assert ties == [] and rows[0]["expected_dataset_id"] == "list-3"


def test_real_sets_after_normalization_hold_invariants():
    from tools.case_to_gold import load_catalog, name_key, normalize_rows
    cat = load_catalog()
    for rel in ("docs/LCA/data/gold/case-v2.csv", "docs/LCA/data/gold/dev-v2.csv"):
        _, header, parsed = read_csv(ROOT / rel)
        assert validate(header, parsed, list_ids()) == []
        rows = [r for _, r in parsed]
        for r in rows:
            a, s = r["a_accept"].split("|"), [x for x in r["s_accept"].split("|") if x]
            assert r["label_type"] != "exact" or s
            assert r["label_type"] == "none" or r["expected_dataset_id"] == a[0]
            assert len({name_key(d, cat) for d in s}) == len(s)  # 한 행의 S 에 같은 이름 묶음 둘 이상 없음
        assert normalize_rows(rows, cat) == ([], [])  # 이미 정규화됨(멱등)
