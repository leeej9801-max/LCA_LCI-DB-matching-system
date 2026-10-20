"""E2: 사전(D)·Veto(V)·동명 접기(G)·케이스 표기·신뢰도 규칙 후보·외부 결과 내보내기/가져오기."""
import csv
import hashlib
import json
from pathlib import Path

import psycopg
import pytest

from app.bom.infer_role import infer_role, veto_role
from app.bom.lexicon import FORM_WORDS, expand
from app.evaluation import confidence_rules as cr
from app.evaluation.cases import VETO_EXCLUDE, fold_ranking, ladder_key, parse_case
from app.evaluation.export_candidates import FORBIDDEN, export, export_rows
from app.evaluation.gold import load
from app.evaluation.import_external import import_file, validate
from app.evaluation.run import paired, run_eval
from test_evaluation_gold import evaldb, write_gold  # noqa: F401  (fixture 재사용)
from test_indexer import FakeEmbedder
from test_migrate import needs_db, tempdb  # noqa: F401

DATA = Path(__file__).parents[2] / "docs/LCA/data"
DIGEST = ("sha256:fake", None)


# ---------- D 사전 ----------
def test_lexicon_appends_synonyms_and_keeps_original():
    dense, tfidf, hits = expand("PP 사출")
    assert dense == "PP 사출 폴리프로필렌 사출성형" and tfidf == dense and hits == ["PP→폴리프로필렌", "사출→사출성형"]
    assert expand("PPS 수지")[2] == []  # 영문 키는 단어 경계: PPS 안의 PP 는 아님
    assert expand("PET 필름")[2] == ["PET→폴리에틸렌 테레프탈레이트"]  # PE 가 PET 안에서 걸리지 않음
    assert expand("사출성형")[2] == []  # 값이 이미 있으면 덧붙이지 않는다


def test_lexicon_drops_form_words_only_from_tfidf():
    dense, tfidf, hits = expand("ABS 수지 펠릿")
    assert "펠릿" in dense and "펠릿" not in tfidf and "-펠릿" in hits
    assert tfidf.startswith("ABS 수지") and all(w not in tfidf for w in FORM_WORDS)


# ---------- V 소재 추정 ----------
@pytest.mark.parametrize("name,role", [
    ("ABS 수지 펠릿", "material"), ("PC 수지", "material"), ("SGCC 용융아연도금강판", "material"), ("GI 코일", "material"),
    ("POM 아세탈 레진", "material"), ("SWRCH10A 선재", "material"),
    ("ABS 사출", "process"), ("프레스 가공", "process"), ("분체도장 처리", "process"),
    ("SPCC 냉연강판 1.2T", None), ("냉간압연강판", None),  # '압연'(공정)이 함께 있어 모른다
    ("볼트 M6x20", None), ("고밀도 폴리에틸렌 HDPE", None), ("압출 필름", None), ("", None),
])
def test_veto_role_table(name, role):
    assert veto_role(name)[0] == role


def test_infer_role_for_app_is_unchanged():
    assert infer_role("ABS 수지 펠릿")[0] is None and infer_role("PC 수지")[0] is None  # 앱은 여전히 소재를 추정하지 않는다


def _fp(rows):
    """오탐: 추정 소재인데 정답 역할이 공정, 추정 공정인데 정답 역할이 소재(정답이 필터에서 빠지는 경우)."""
    out = {"hit": 0, "miss": 0, "fp": []}
    for name, truth in rows:
        got = veto_role(name)[0]
        if (got == "material" and truth == "공정") or (got == "process" and truth == "소재"):
            out["fp"].append(name)
        elif got:
            out["hit"] += 1
        elif truth in ("소재", "공정"):
            out["miss"] += 1
    return out


@pytest.mark.skipif(not (DATA / "sample-bom-split-draft.csv").exists(), reason="개발 샘플 없음")
def test_veto_no_false_positive_on_sample_19():
    rows = [(r["품명"], r["구분"]) for r in csv.DictReader((DATA / "sample-bom-split-draft.csv").open(encoding="utf-8-sig"))]
    t = _fp(rows)
    assert t["fp"] == [] and t["hit"] == 13 and t["miss"] == 6


@pytest.mark.skipif(not (DATA / "gold/dev-v2.csv").exists(), reason="dev-v2 없음")
def test_veto_no_false_positive_on_dev_v2():
    rows = list(csv.DictReader((DATA / "gold/dev-v2.csv").open(encoding="utf-8-sig")))
    t = _fp([(r["bom_text"], r["expected_role"]) for r in rows])
    assert t["fp"] == [] and t["hit"] > 0


def test_veto_never_excludes_combined():
    assert "combined" not in VETO_EXCLUDE.values() and set(VETO_EXCLUDE.values()) == {"process", "material"}


# ---------- 케이스 표기 ----------
def test_parse_case_aliases_and_order():
    assert parse_case("C3")["canonical"] == "C2+D" and parse_case("C4")["canonical"] == "C2+D+V"
    p = parse_case("C1+V+D+G")
    assert p["canonical"] == "C1+G+D+V" and p["base"] == "C1" and p["elements"] == {"G", "D", "V"}
    x = parse_case("C4+X:x-rerank-abc")
    assert x["canonical"] == "C2+D+V+X:x-rerank-abc" and x["run"] == "x-rerank-abc"
    assert parse_case("C5")["pending"] is True
    for bad in ("C9", "C2+Q", "C2+X:", "C2+X:a+X:b"):
        with pytest.raises(SystemExit):
            parse_case(bad)
    assert sorted(["C2+D+V", "C0", "C2+D", "C1", "C2"], key=ladder_key) == ["C0", "C1", "C2", "C2+D", "C2+D+V"]


def test_fold_ranking_uses_newest_edition_at_first_position():
    cat = {"list-1": ("냉연강판", 2003, 1), "list-2": ("냉연강판", 2022, 2), "list-3": ("열연강판", 2022, 3)}
    assert fold_ranking([("list-1", 0.9), ("list-3", 0.8), ("list-2", 0.7)], cat) == [("list-2", 0.9), ("list-3", 0.8)]


def test_paired_counts_new_right_and_wrong():
    def r(lid, top, exp):
        return {"label_id": lid, "ranking": [(top, 1.0)], "expected": exp, "a_accept": [exp], "s_accept": [exp]}
    base = [r(1, "a", "a"), r(2, "x", "b"), r(3, "c", "c")]
    case = [r(1, "a", "a"), r(2, "b", "b"), r(3, "x", "c")]
    assert paired({"C2": base, "C2+D": case}, "C2")["cases"]["C2+D"] == {"new_right": [2], "new_wrong": [3]}
    assert paired({"C1": base}, "C2") is None
    from app.evaluation.run import pair_counts
    pc = pair_counts({"C2": base, "C2+D": case}, "C2")["cases"]["C2+D"]
    assert pc["A"] == {"new_right": 1, "new_wrong": 1, "same": 1, "rows": 3} and pc["S"] == pc["A"]
    assert pair_counts({"C1": base}, "C2") is None


# ---------- 신뢰도 규칙 후보 ----------
ROW_HIGH = {"rank_tfidf": 1, "rank_dense": 1, "score_dense": 0.62, "gap_dense": 0.02}


def test_rule_candidates_judge():
    assert cr.judge(ROW_HIGH, "R0", {}) == "높음"
    assert cr.judge(ROW_HIGH, "R1", {"tau": 0.60}) == "높음" and cr.judge(ROW_HIGH, "R1", {"tau": 0.65}) == "보통"
    assert cr.judge(ROW_HIGH, "R2", {"delta": 0.02}) == "높음" and cr.judge(ROW_HIGH, "R2", {"delta": 0.03}) == "보통"
    assert cr.judge(ROW_HIGH, "R3", {"tau": 0.60, "delta": 0.03}) == "보통"
    assert cr.judge({"rank_tfidf": 2, "rank_dense": 9, "score_dense": 0.99, "gap_dense": 0.5}, "R1", {"tau": 0.5}) == "낮음"  # 낮음은 그대로
    assert cr.judge({"rank_tfidf": 1, "rank_dense": 1, "score_dense": None, "gap_dense": None}, "R3", {"tau": 0.5, "delta": 0.01}) == "보통"
    assert len(cr.candidates()) == 1 + len(cr.TAU_GRID) + len(cr.DELTA_GRID) + len(cr.TAU_GRID) * len(cr.DELTA_GRID)


def test_rule_selection_criterion():
    t = [{"name": "R0", "rule": "R0", "high_error_A": 0.15, "high_coverage": 0.51},
         {"name": "R1 a", "rule": "R1", "high_error_A": 0.08, "high_coverage": 0.46},
         {"name": "R3 a", "rule": "R3", "high_error_A": 0.08, "high_coverage": 0.47},
         {"name": "R2 a", "rule": "R2", "high_error_A": 0.02, "high_coverage": 0.30}]
    assert cr.select(t) == "R1 a"  # 45% 이상 중 오류율 최소, 같으면 단순한 것
    assert cr.select(t, 0.30) == "R2 a" and cr.select(t, 0.9) is None


def test_rule_compare_stats_and_ci():
    rows = [ROW_HIGH | {"ok_A": 1, "ok_strict": 1}, ROW_HIGH | {"score_dense": 0.55, "ok_A": 0, "ok_strict": 0},
            {"rank_tfidf": 2, "rank_dense": 2, "score_dense": 0.5, "gap_dense": 0.0, "ok_A": 1, "ok_strict": 0}]
    out = cr.compare(rows)
    r0 = next(t for t in out["candidates"] if t["name"] == "R0")
    assert r0["levels"]["높음"]["rows"] == 2 and r0["high_error_A"] == 0.5 and abs(r0["high_coverage"] - 2 / 3) < 1e-9
    r1 = next(t for t in out["candidates"] if t["name"] == "R1 τ=0.60")
    assert r1["high_error_A"] == 0.0 and r1["levels"]["보통"]["rows"] == 2
    lo, hi = r0["ci"]["high_error_A"]
    assert 0 <= lo <= 0.5 <= hi <= 1


# ---------- 내보내기·가져오기 ----------
def keys_deep(x):
    if isinstance(x, dict):
        return set(x) | set().union(*(keys_deep(v) for v in x.values())) if x else set()
    if isinstance(x, list):
        return set().union(*(keys_deep(v) for v in x)) if x else set()
    return set()


def test_export_rows_has_no_answer_columns():
    labels = [{"label_id": 1, "bom_text": "PP 수지", "spec": None, "unit": "kg", "expected_dataset_id": "list-4", "a_accept": ["list-4"], "note": "x"}]
    ds = {"list-4": {"name_ko": "폴리프로필렌", "name_en": "PP", "category": "화학물질", "role": "소재", "org": "o", "year": 2024}}
    rows = export_rows(labels, [[("list-4", 0.9)]], [{"inferred_role": "material"}], ds, 30)
    assert not (keys_deep(rows) & FORBIDDEN) and rows[0]["candidates"][0]["rank"] == 1


EXPORT = {"export_id": "e1", "rows": [{"label_id": 1, "candidates": [{"dataset_id": "list-1"}, {"dataset_id": "list-2"}]},
                                      {"label_id": 2, "candidates": [{"dataset_id": "list-3"}]}]}
GOOD = {"export_id": "e1", "export_sha256": "s", "run": {"kind": "rerank", "model": "m", "params": {}},
        "results": [{"label_id": 1, "ranking": [["list-2", 0.9], ["list-1", 0.1]]}, {"label_id": 2, "ranking": [["list-3", 0.5]]}]}


def test_import_validation_rejects_bad_files():
    assert validate(GOOD, EXPORT, "s") == []
    assert any("sha256" in e for e in validate(GOOD, EXPORT, "other"))
    bad_id = json.loads(json.dumps(GOOD))
    bad_id["results"][0]["ranking"][0][0] = "list-99"
    assert any("내보낸 후보에 없는 id" in e for e in validate(bad_id, EXPORT, "s"))
    missing = json.loads(json.dumps(GOOD))
    missing["results"].pop()
    assert any("결과가 없는 행" in e for e in validate(missing, EXPORT, "s"))
    judge = json.loads(json.dumps(GOOD))
    judge["run"]["kind"] = "judge"
    assert any("decision" in e for e in validate(judge, EXPORT, "s"))
    judge["results"][0] |= {"decision": "pick", "picked_dataset_id": "list-3"}  # 다른 행의 후보
    judge["results"][1] |= {"decision": "none"}
    assert [e for e in validate(judge, EXPORT, "s") if "picked" in e]
    unknown = json.loads(json.dumps(GOOD))
    unknown["results"].append({"label_id": 9, "ranking": []})
    assert any("내보내기에 없는 행" in e for e in validate(unknown, EXPORT, "s"))


@pytest.fixture
def e2db(evaldb, tmp_path):  # noqa: F811
    """합성 데이터셋에 역할을 붙이고 정답셋 t/v1 적재."""
    roles = {"list-1": "material", "list-2": "material", "list-3": "material", "list-4": "material", "list-5": "utility",
             "list-6": "combined", "list-7": "process", "list-8": "utility", "list-9": "utility", "list-10": "material"}
    with psycopg.connect(evaldb) as conn:
        for d, r in roles.items():
            conn.execute("UPDATE lci_dataset SET role = %s, dev_year = %s WHERE dataset_id = %s", (r, 2022 if d == "list-2" else 2003, d))
    load(evaldb, write_gold(tmp_path / "g.csv"), "t", "v1")
    return evaldb


@needs_db
def test_run_combinations_report(e2db, tmp_path):
    report, out = run_eval(e2db, FakeEmbedder(), "t", ["C2", "C2+D", "C2+V", "C2+G+D+V", "C1+G+D+V"], out=tmp_path / "o", digest=DIGEST)
    assert all(report["cases"][c]["state"] == "measured" for c in report["cases"])
    assert set(report["paired"]["cases"]) == {"C2+D", "C2+V", "C2+G+D+V", "C1+G+D+V"}
    assert set(report["confidence_rules"]) == set(report["cases"]) and set(report["no_answer_by_case"]) == set(report["cases"])
    assert "expected_role" in report["slices"]["C2"] and "hard_pair_value" in report["slices"]["C2"]
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "## 짝 비교" in md and "## 신뢰도 규칙 후보 — C2" in md


@needs_db
def test_export_import_and_external_case(e2db, tmp_path):
    with pytest.raises(SystemExit, match="--final"):
        export(e2db, FakeEmbedder(), "t", "test", "C2+D+V", 5, out=tmp_path / "x.json")
    export_id, sha, path = export(e2db, FakeEmbedder(), "t", "dev", "C4", 5, out=tmp_path / "exp.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["base_case"] == "C2+D+V" and doc["top"] == 5 and hashlib.sha256(path.read_bytes()).hexdigest() == sha
    assert not (keys_deep(doc) & FORBIDDEN) and all(len(r["candidates"]) <= 5 for r in doc["rows"])
    with psycopg.connect(e2db) as conn:
        assert conn.execute("SELECT split, base_case, top FROM eval_export WHERE export_id = %s", (export_id,)).fetchone() == ("dev", "C2+D+V", 5)

    # 재순위: 후보 순서를 뒤집은 결과
    result = {"export_id": export_id, "export_sha256": sha, "run": {"kind": "rerank", "model": "fake-rerank", "params": {"k": 1}},
              "results": [{"label_id": r["label_id"], "ranking": [[c["dataset_id"], 1.0 / c["rank"]] for c in reversed(r["candidates"])]}
                          for r in doc["rows"]]}
    rp = tmp_path / "res.json"
    rp.write_text(json.dumps(result), encoding="utf-8")
    run_id, created = import_file(e2db, rp, path)
    assert created and run_id.startswith("x-rerank-") and import_file(e2db, rp, path) == (run_id, False)
    report, _ = run_eval(e2db, FakeEmbedder(), "t", [f"C4+X:{run_id}"], out=tmp_path / "r", digest=DIGEST)
    assert report["external_runs"][f"C4+X:{run_id}"]["model"] == "fake-rerank"

    # 판정: 모두 none → 그 케이스의 no_answer 는 전부
    judge = {**result, "run": {"kind": "judge", "model": "fake-judge", "structure": "S1"},
             "results": [{**r, "decision": "none", "picked_dataset_id": None} for r in result["results"]]}
    jp = tmp_path / "judge.json"
    jp.write_text(json.dumps(judge), encoding="utf-8")
    jid, _ = import_file(e2db, jp, path)
    report, _ = run_eval(e2db, FakeEmbedder(), "t", [f"C2+D+V+X:{jid}"], out=tmp_path / "j", digest=DIGEST)
    na = report["no_answer_by_case"][f"C2+D+V+X:{jid}"]
    assert na["answerable"]["no_answer"] == na["answerable"]["rows"] and na["none"]["no_answer"] == na["none"]["rows"]
    with pytest.raises(SystemExit, match="기준"):  # 다른 기준 케이스에 붙이면 거부
        run_eval(e2db, FakeEmbedder(), "t", [f"C2+X:{jid}"], out=tmp_path / "k", digest=DIGEST)

    # 잘못된 파일은 전부 거부(아무것도 쓰지 않음)
    for broken in ({**result, "export_sha256": "0" * 64},
                   {**result, "results": result["results"][1:]},
                   {**result, "results": [{**result["results"][0], "ranking": [["list-999", 1.0]]}] + result["results"][1:]}):
        bp = tmp_path / "broken.json"
        bp.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(SystemExit, match="가져오지 않았습니다"):
            import_file(e2db, bp, path)
    with psycopg.connect(e2db) as conn:
        assert conn.execute("SELECT count(*) FROM eval_external_run").fetchone()[0] == 2


@needs_db
def test_external_case_accepts_g_export_but_rejects_other_base(e2db, tmp_path):
    export_id, sha, path = export(e2db, FakeEmbedder(), "t", "dev", "C1+G+D+V", 5, out=tmp_path / "g.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["base_case"] == "C1+G+D+V"
    result = {"export_id": export_id, "export_sha256": sha, "run": {"kind": "rerank", "model": "fake-rerank", "params": {"k": 1}},
              "results": [{"label_id": r["label_id"], "ranking": [[c["dataset_id"], 1.0 / c["rank"]] for c in r["candidates"]]} for r in doc["rows"]]}
    rp = tmp_path / "g-res.json"
    rp.write_text(json.dumps(result), encoding="utf-8")
    run_id, _ = import_file(e2db, rp, path)
    report, _ = run_eval(e2db, FakeEmbedder(), "t", [f"C1+G+D+V+X:{run_id}"], out=tmp_path / "ok", digest=DIGEST)
    assert report["cases"][f"C1+G+D+V+X:{run_id}"]["state"] == "measured"
    for other in (f"C1+G+D+X:{run_id}", f"C2+G+D+V+X:{run_id}"):  # D·V 부분이나 C 기준이 다르면 거부
        with pytest.raises(SystemExit, match="기준"):
            run_eval(e2db, FakeEmbedder(), "t", [other], out=tmp_path / "bad", digest=DIGEST)


# ---------- E2b ----------
def test_lexicon_origin_covers_every_key():
    from app.bom.lexicon import FORM_WORDS, ORIGIN, ORIGINS, SYNONYMS
    keys = set(SYNONYMS) | set(FORM_WORDS)
    assert keys == set(ORIGIN) and set(ORIGIN.values()) <= set(ORIGINS)
    assert ORIGIN["PP"] == "std" and ORIGIN["HDPE"] == "db" and ORIGIN["시너"] == "dev" and ORIGIN["펠릿"] == "dev"


def test_lexicon_non_dev_origin_filter():
    from app.bom.lexicon import NON_DEV, expand, hit_origin
    assert expand("PP 시너", NON_DEV)[2] == ["PP→폴리프로필렌"]  # 시너(dev)는 빠진다
    assert expand("PP 시너")[2] == ["PP→폴리프로필렌", "시너→신나"] and hit_origin("시너→신나") == "dev" and hit_origin("PP→폴리프로필렌") == "std"
    dense, tfidf, hits = expand("ABS 수지 펠릿", NON_DEV)
    assert "펠릿" in tfidf and not any(h.startswith("-") for h in hits)  # 형태어는 전부 dev 출처라 Ds 에서는 빼지 않는다
    assert hit_origin("-펠릿") == "dev"


def test_parse_case_ds_vd():
    p = parse_case("C2+Vd+Ds+G")
    assert p["canonical"] == "C2+G+Ds+Vd" and p["elements"] == {"G", "Ds", "Vd"}
    from app.evaluation.cases import base_without_x, modes
    assert modes(p) == ("Ds", "Vd") and base_without_x(parse_case("C2+Ds+Vd+X:r")) == "C2+Ds+Vd" and modes(parse_case("C2")) == (None, None)
    for bad in ("C2+D+Ds", "C2+V+Vd"):
        with pytest.raises(SystemExit, match="함께 쓰지"):
            parse_case(bad)


def test_demote_keeps_order_and_leaves_combined():
    from app.evaluation.cases import demote, effective_role
    roles = {"a": "process", "b": "material", "c": "combined", "d": "process", "e": "material"}
    rk = [("a", 5), ("b", 4), ("c", 3), ("d", 2), ("e", 1)]
    assert [d for d, _ in demote(rk, roles, "process")] == ["b", "c", "e", "a", "d"]  # process 만 뒤로, 각 묶음 안은 원래 순서, 합본(c) 자리 불변
    assert demote(rk, roles, "plastic") == rk
    assert effective_role("PC 수지") == "material" and effective_role("PC 수지", "process") == "process"  # 입력 구분 우선
    assert effective_role("볼트 M6x20", "material") == "material" and effective_role("볼트 M6x20") is None


def test_recall_at_k_by_hand():
    from app.evaluation.metrics import rank_worse, recall_at
    def r(lid, ids, acc, s=None):
        return {"label_id": lid, "expected": acc[0] if acc else None, "ranking": [(d, 1.0) for d in ids], "a_accept": acc or None, "s_accept": acc if s is None else s}
    rows = [r(1, ["x", "a"], ["a"]), r(2, ["a"], ["a"]), r(3, ["q"] * 3 + ["a"], ["a"]), r(4, ["z"], ["a"]), r(5, ["a"], [], None), r(6, ["a"], ["a"], [])]
    rows[4] = {"label_id": 5, "expected": None, "ranking": [("a", 1.0)], "a_accept": None, "s_accept": None}  # none 행: 제외
    a = recall_at(rows, "A", ks=(1, 3, 10, 30))
    assert a["n"] == 5 and a["top1"] == 2 / 5 and a["top3"] == 3 / 5 and a["top10"] == 4 / 5 and a["miss_ids"] == [4]
    s = recall_at(rows, "S")  # 6번은 s_accept 가 비어 S 분모 밖
    assert s["n"] == 4 and s["top1"] == 1 / 4 and s["miss_ids"] == [4]
    before = {"expected": "a", "ranking": [("a", 1.0)], "a_accept": ["a"], "s_accept": ["a"]}
    assert rank_worse(before, {**before, "ranking": [("b", 1), ("a", 1)]}) and rank_worse(before, {**before, "ranking": [("b", 1)]})
    assert not rank_worse(before, before) and not rank_worse({**before, "ranking": [("b", 1), ("a", 1)]}, before)
    assert not rank_worse({"expected": None, "ranking": [], "a_accept": None, "s_accept": None}, before)


def test_gold_header_synthetic_warning():
    from app.evaluation.metrics import SYNTHETIC_WARNING, gold_header
    claude = [{"decided_by": "claude"}] * 3 + [{"decided_by": "user"}] * 2 + [{"decided_by": "user+claude"}]
    h = gold_header(claude)
    assert h["claude_ratio"] == 0.5 and h["synthetic_warning"] is None  # 정확히 50% 는 넘지 않음
    h = gold_header(claude + [{"decided_by": "claude"}])
    assert h["synthetic_warning"] == SYNTHETIC_WARNING and abs(h["claude_ratio"] - 4 / 7) < 1e-9
    assert gold_header([{"decided_by": "user"}])["synthetic_warning"] is None


def test_rule_constants_and_verdict_wording():
    assert (cr.HIGH_RATIO_MIN, cr.HIGH_ERR_GOAL, cr.HIGH_ERR_PASS) == (0.45, 0.05, 0.10) and cr.COVERAGE_MIN == cr.HIGH_RATIO_MIN
    ok = {"high_coverage": 0.50, "high_error_A": 0.075, "ci": {"high_error_A": [0.016, 0.145]}}
    v = cr.verdict(ok)
    assert v["pass_point"] is True and v["goal_guarantee"] is False
    text = "\n".join(cr.verdict_lines(ok))
    assert "합격(점추정): 예" in text and "보증(구간 상한 ≤ 5%): 아니오" in text and "5% 이하 달성" not in text and "1.6%~14.5%" in text
    assert cr.verdict({**ok, "high_coverage": 0.40})["pass_point"] is False and cr.verdict({**ok, "high_error_A": 0.11})["pass_point"] is False
    sure = {"high_coverage": 0.50, "high_error_A": 0.01, "ci": {"high_error_A": [0.0, 0.049]}}
    assert cr.verdict(sure)["goal_guarantee"] is True and "5% 이하 달성(구간 상한 4.9%)" in "\n".join(cr.verdict_lines(sure))
    assert cr.verdict({"high_coverage": 0.5, "high_error_A": 0.01, "ci": None})["goal_guarantee"] is False  # 구간 없으면 보증하지 않음


def test_paired_extra_and_lexicon_hit_rates():
    from app.evaluation.run import lexicon_hit_rates, paired_extra
    def r(lid, top, exp):
        return {"label_id": lid, "ranking": [(top, 1.0)], "expected": exp, "a_accept": [exp], "s_accept": [exp]}
    rb = {"C4": [r(1, "a", "a"), r(2, "x", "b")], "C2+Ds+V": [r(1, "x", "a"), r(2, "b", "b")], "C2+D+Vd": [r(1, "a", "a"), r(2, "x", "b")]}
    canon = {"C2+D+V": "C4", "C2+Ds+V": "C2+Ds+V", "C2+D+Vd": "C2+D+Vd"}
    got = paired_extra(rb, canon)
    assert [(x["base"], x["case"], x["new_right"], x["new_wrong"]) for x in got] == [("C4", "C2+Ds+V", [2], [1]), ("C4", "C2+D+Vd", [], [])]
    assert paired_extra({"C2": []}, {"C2": "C2"}) == []
    meta = [{"lexicon_hits": ["PP→폴리프로필렌", "시너→신나"]}, {"lexicon_hits": []}, {"lexicon_hits": ["-펠릿"]}, {"lexicon_hits": ["SPCC→냉간압연강판"]}]
    assert lexicon_hit_rates(meta, "D") == {"mode": "D", "rows": 4, "any": 3, "std": 2, "db": 0, "dev": 2}


@needs_db
def test_run_e2b_report_sections(e2db, tmp_path):
    cases = ["C2", "C2+D+V", "C2+Ds+V", "C2+D+Vd"]
    report, out = run_eval(e2db, FakeEmbedder(), "t", cases, out=tmp_path / "o", digest=DIGEST)
    assert [(x["base"], x["case"]) for x in report["paired_extra"]] == [("C2+D+V", "C2+Ds+V"), ("C2+D+V", "C2+D+Vd")]
    assert set(report["recall_at_k"]) == set(cases) and report["recall_at_k"]["C2"]["A"]["top30"] >= report["recall_at_k"]["C2"]["A"]["top1"]
    assert set(report["lexicon_hits"]) == {"C2+D+V", "C2+Ds+V", "C2+D+Vd"} and report["lexicon_hits"]["C2+Ds+V"]["mode"] == "Ds"
    assert set(report["veto_hurt"]) == {"C2+D+V", "C2+Ds+V", "C2+D+Vd"} and all(isinstance(v["ids"], list) for v in report["veto_hurt"].values())
    md = (out / "report.md").read_text(encoding="utf-8")
    for h in ("## 후보 재현율", "## 사전 적중 행 비율", "## 짝 비교 — C2+D+V 대비 C2+Ds+V", "## Veto로 정답 순위가 나빠진 행", "① 합격(점추정)"):
        assert h in md
    assert report["gold_stats"]["synthetic_warning"] is None  # 합성 정답셋 시험 파일은 decided_by 가 비어 있다
    ds = next(c for c in report["cases"] if c == "C2+Ds+V")
    assert report["cases"][ds]["state"] == "measured"


def test_veto_hurt_splits_target_role_from_other_drops():
    from app.evaluation.run import veto_hurt
    def r(lid, ids, acc):
        return {"label_id": lid, "expected": acc[0], "ranking": [(d, 1.0) for d in ids], "a_accept": acc, "s_accept": acc}
    roles = {"p1": "process", "m1": "material", "m2": "material"}
    # 1: 소재로 추정, 정답이 공정 데이터셋(거른 역할)이라 밀림 / 2: 정답은 소재인데 순위만 하락 / 3: 변화 없음
    rows = [r(1, ["m1", "p1"], ["p1"]), r(2, ["m2", "m1"], ["m1"]), r(3, ["m1"], ["m1"])]
    before = [[("p1", 1.0), ("m1", 1.0)], [("m1", 1.0), ("m2", 1.0)], [("m1", 1.0)]]
    meta = [{"inferred_role": "material"}] * 3
    assert veto_hurt(rows, before, meta, roles) == {"n": 1, "ids": [1], "other_n": 1, "other_ids": [2]}
    assert veto_hurt(rows, before, [{"inferred_role": None}] * 3, roles) == {"n": 0, "ids": [], "other_n": 2, "other_ids": [1, 2]}
