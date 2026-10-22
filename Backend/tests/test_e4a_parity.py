"""E4a: 앱 검색 경로가 평가 케이스(C2+D+Vd / C1+D+Vd, R1 τ=0.55)와 dev-v2 전체 행에서 같은 결과를 내는지, 설정·근거 문구.

parity 시험은 임시 DB 에 849 목록 전체(+역할)를 넣고 가짜 임베더로 인덱스를 만든다. 849 목록과 dev-v2 파일이 없으면 건너뛴다.
"""
import csv
import hashlib
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app import roles
from app.bom import match
from app.bom.lexicon import origin_counts, synonyms_sha256
from app.bom.veto import demoted_note
from app.db.migrate import migrate
from app.evaluation import metrics
from app.evaluation.confidence_rules import judge
from app.evaluation.cases import run_cases
from app.indexer import build_index
from test_bom_match import ITEM, bomdb, ranked, add_session  # noqa: F401  (fixture 재사용)
from test_indexer import FakeEmbedder, quiet
from test_migrate import needs_db, tempdb  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
LIST = ROOT / "docs/LCA/data/lci-db-list-ecosq-849.csv"
DEV = ROOT / "docs/LCA/data/gold/dev-v2.csv"
needs_data = pytest.mark.skipif(not (LIST.exists() and DEV.exists()), reason="849 목록 또는 dev-v2 파일 없음")
TAU = 0.55


def settings(base="dense", lexicon="D", veto="Vd", rule="R1", params=None):
    return {"search_base": base, "lexicon_mode": lexicon, "veto_mode": veto,
            "confidence": {"rule": rule, "params": {"tau": TAU} if params is None and rule == "R1" else (params or {})}}


# ---------- 순수 함수: 설정 ----------
def test_default_settings_are_the_e4a_choice():
    assert (match.SEARCH_BASE, match.LEXICON_MODE, match.VETO_MODE, match.CONFIDENCE) == ("dense", "D", "Vd", ("R1", {"tau": 0.55}))  # E4c: C1+G+D+Vd
    assert match.current_settings() == settings()
    assert match.check_settings(match.current_settings()) == match.current_settings()


def test_current_settings_reads_module_constants_at_call_time(monkeypatch):
    monkeypatch.setattr(match, "SEARCH_BASE", "dense")
    monkeypatch.setattr(match, "LEXICON_MODE", None)
    monkeypatch.setattr(match, "CONFIDENCE", ("R0", {}))
    assert match.current_settings() == settings("dense", None, "Vd", "R0", {})


@pytest.mark.parametrize("cfg", [settings(), settings("rrf"), settings(lexicon=None), settings(lexicon="Ds"), settings(veto=None), settings(veto="V"),
                                 settings(rule="R0", params={}), settings(params={"tau": 0.6})])
def test_valid_settings_combinations_parse(cfg):
    assert match.check_settings(cfg) is cfg


@pytest.mark.parametrize("cfg", [settings("hybrid"), settings(lexicon="X"), settings(veto="Vx"), settings(rule="R2", params={"delta": 0.02}),
                                 settings(rule="R1", params={}), settings(rule="R0", params={"tau": 0.5}), settings(rule="R1", params={"tau": "x"}),
                                 settings(rule="R1", params={"tau": 0.5, "delta": 0.1})])
def test_invalid_settings_are_rejected(cfg):
    with pytest.raises(ValueError):
        match.check_settings(cfg)


def test_rule_text_mentions_r1_only_when_used():
    assert match.confidence_rule_text(settings(rule="R0", params={})) == match.CONFIDENCE_RULE
    text = match.confidence_rule_text(settings())
    assert text.startswith(match.CONFIDENCE_RULE) and "R1" in text and "0.55" in text


def test_lexicon_helpers_for_config():
    c = origin_counts()
    assert c["total"] == c["synonyms"] + c["form_words"] == c["std"] + c["db"] + c["dev"] == 38 and (c["std"], c["db"], c["dev"]) == (16, 6, 16)
    assert synonyms_sha256() == synonyms_sha256() and len(synonyms_sha256()) == 64


# ---------- 순수 함수: 근거 문구 ----------
def item(name, norm=None, role=None):
    return dict(ITEM) | {"clean_name": name, "norm_text": norm or name, "input_role": role}


CFG = {"lexicon_mode": "D", "veto_mode": "Vd"}


def reasons(it, cands, cfg=CFG):
    return [c["reasons"] for c in match.row_payload(it, cands, {}, None, cfg)["candidates"]]


def test_lexicon_line_max_two_items():
    assert match.lexicon_line("PP 사출", "D") == "사전: PP → 폴리프로필렌, 사출 → 사출성형"
    assert match.lexicon_line("ABS PP 사출", "D") == "사전: PP → 폴리프로필렌, ABS → 아크릴로니트릴 부타디엔 스티렌"  # 적중 3개 중 앞의 2개만
    assert match.lexicon_line("볼트 M6x20", "D") is None and match.lexicon_line("PP 사출", None) is None
    assert match.lexicon_line("ABS 시너", "Ds") == "사전: ABS → 아크릴로니트릴 부타디엔 스티렌" and match.lexicon_line("시너", "D") == "사전: 시너 → 신나"
    assert match.lexicon_line("ABS 펠릿", "D") == "사전: ABS → 아크릴로니트릴 부타디엔 스티렌"  # 형태어 제거(-펠릿)는 동의어가 아니라 보이지 않는다


def test_demoted_note_text():
    assert demoted_note("material", "process") == "역할 다름(소재 입력에 공정 데이터셋) → 뒤로"
    assert demoted_note("process", "material") == "역할 다름(공정 입력에 소재 데이터셋) → 뒤로"
    assert demoted_note("material", "combined") is None and demoted_note("material", "material") is None and demoted_note(None, "process") is None


def test_row_reasons_show_dictionary_and_demoted_candidates():
    cands = [ranked("가", 1, 1) | {"role": "process"}, ranked("나", 2, 2) | {"role": "material"}, ranked("다", 3, 3) | {"role": "combined"}]
    r = reasons(item("PC 수지"), cands)  # 소재로 추정(수지) → 공정 후보만 뒤로
    assert "사전: PC → 폴리카보네이트" in r[0] and "역할 다름(소재 입력에 공정 데이터셋) → 뒤로" in r[0]
    assert not any("역할 다름" in x for x in r[1] + r[2]) and all("사전: PC → 폴리카보네이트" in x for x in r)  # 소재·합본은 안 밀림, 사전은 질의 단위라 모든 후보에
    r = reasons(item("PP 사출"), cands)  # 공정으로 추정 → 소재 후보가 뒤로, 추정 표시는 그대로
    assert "역할 다름(공정 입력에 소재 데이터셋) → 뒤로" in r[1] and "구분 '공정'을 이름에서 자동 추정" in r[0] and "공정 아닌 후보는 뒤로" in r[0]
    assert not any("공정 데이터셋 안에서 찾음" in x for rs in r for x in rs)
    # 입력 구분이 있으면 하드 필터 문구만, 강등 문구 없음
    r = reasons(item("PP 사출", role="process"), cands)
    assert "구분 '공정' → 공정 데이터셋 안에서 찾음" in r[0] and not any("역할 다름" in x for rs in r for x in rs)


def test_old_runs_and_missing_config_add_no_lines():
    cands = [ranked("가", 1, 1) | {"role": "process"}]
    for cfg in (None, {}, {"lexicon_mode": None, "veto_mode": None}, {"top_n": 20, "confidence_rule": "옛 규칙"}):
        [r] = reasons(item("PC 수지"), cands, cfg)
        assert not any(x.startswith("사전:") or "역할 다름" in x for x in r)
    assert match.row_payload(item("PC 수지"), cands, {}, None, None)["inferred_role"] is None  # 화면 표시(추정 구분)는 그대로


# ---------- config 기록 ----------
@needs_db
def test_match_run_records_the_e4a_settings(bomdb):  # noqa: F811
    for cfg in (None, settings("dense", "Ds", "V", "R0", {})):
        sid = add_session(bomdb, ["냉연강판"], "abcdefABCDE1" if cfg is None else "abcdefABCDE2")
        with psycopg.connect(bomdb) as conn:
            match.CACHE.data.clear()
            r = match.match_project(conn, sid, FakeEmbedder(), settings=cfg)
            config = conn.execute("SELECT config FROM match_run WHERE run_id = %s", (r["run_id"],)).fetchone()[0]
        want = cfg or match.current_settings()
        assert (config["search_base"], config["lexicon_mode"], config["veto_mode"], config["confidence"]) == (
            want["search_base"], want["lexicon_mode"], want["veto_mode"], want["confidence"])
        assert config["lexicon"] == {**origin_counts(), "synonyms_sha256": synonyms_sha256()} and config["confidence_rule"] == match.confidence_rule_text(want)
        assert config["query"].startswith("norm_text(") and config["role_filter_rule"] == match.ROLE_FILTER_RULE
    with psycopg.connect(bomdb) as conn, pytest.raises(ValueError):
        match.match_project(conn, add_session(bomdb, ["열연강판"], "abcdefABCDE3"), FakeEmbedder(), settings=settings("hybrid"))


# ---------- 같은 결과 시험: 앱 경로 대 평가 케이스(dev-v2 전체 134행, 예외 없음) ----------
def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def parity(tempdb):  # noqa: F811
    migrate(tempdb)
    with psycopg.connect(tempdb) as conn:
        for r in read(LIST):
            conn.execute("INSERT INTO lci_dataset (dataset_id, list_sn, name_ko, name_en, category, developer, dev_year, version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                         (f"list-{r['lci_database_sn']}", int(r["lci_database_sn"]), r["name_ko"], r["name_en"], r["category"], r["org"], int(r["year"]), r["version"]))
        roles.apply(conn)  # 앱 DB 와 같은 방법으로 역할을 채운다
    build_index(tempdb, FakeEmbedder(), activate=True, log=quiet)
    match.CACHE.data.clear()
    texts = [r["bom_text"] for r in read(DEV)]
    sid = "paritySess01"
    with psycopg.connect(tempdb) as conn:
        conn.execute("INSERT INTO bom_project (project_id, source_file, expires_at) VALUES (%s, 'dev-v2.csv', now() + interval '1 day')", (sid,))
        for i, t in enumerate(texts, start=1):
            conn.execute("INSERT INTO bom_item (project_id, row_no, source_row, raw_name, raw_spec, raw_unit, raw_qty, clean_name, clean_spec, clean_unit, "
                         "clean_unit_display, clean_qty, norm_text, query_key, issues, target_status, target_reason) "
                         "VALUES (%s,%s,%s,%s,'','kg','1',%s,'','kg','kg',1,%s,%s,%s,'대상','')",
                         (sid, i, i + 1, t, t, t, hashlib.sha1(t.encode("utf-8")).hexdigest()[:16], Jsonb([])))
    return tempdb, sid, texts


def app_candidates(ci, sid, cfg):
    with psycopg.connect(ci) as conn:
        match.CACHE.data.clear()
        r = match.match_project(conn, sid, FakeEmbedder(), settings=cfg)
        got = {}
        for key, rank, ds, conf in conn.execute("SELECT query_key, rank, dataset_id, confidence FROM match_candidate WHERE run_id = %s ORDER BY query_key, rank",
                                                (r["run_id"],)).fetchall():
            got.setdefault(key, []).append((ds, conf))
        conn.commit()
    return got


def eval_expected(ci, texts, case):
    with psycopg.connect(ci) as conn:
        res, _ = run_cases(conn, FakeEmbedder(), texts, [case])
    return res[case]


@needs_data
@needs_db
@pytest.mark.parametrize("base,case", [("rrf", "C2+D+Vd"), ("dense", "C1+D+Vd")])
def test_app_path_equals_evaluation_case_on_every_dev_v2_row(parity, base, case):
    ci, sid, texts = parity
    got = app_candidates(ci, sid, settings(base))
    res = eval_expected(ci, texts, case)
    assert len(texts) == 134 and len(got) == 134
    r1_changed = vd_moved = 0
    for i, text in enumerate(texts):
        key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        order = [d for d, _ in res["rankings"][i][:match.TOP_N]]
        assert [d for d, _ in got[key]] == order, f"후보 순서가 다름: {text!r}"
        # 신뢰도: 후보마다 평가와 같은 함수(judge)를 평가가 쓴 두 목록의 순위·점수로
        t_pos = {d: (r, s) for r, (d, s) in enumerate(res["tfidf"][i], 1)}
        d_pos = {d: (r, s) for r, (d, s) in enumerate(res["dense"][i], 1)}
        want = []
        for ds in order:
            (rt, _), (rd, sd) = t_pos.get(ds, (None, None)), d_pos.get(ds, (None, None))
            want.append(judge({"rank_tfidf": rt, "rank_dense": rd, "score_dense": sd}, "R1", {"tau": TAU}))
        assert [c for _, c in got[key]] == want, f"신뢰도가 다름: {text!r}"
        # 1위의 신뢰도는 평가 리포트가 쓰는 row_detail 경로와도 같다
        row = {"expected": None, "ranking": res["rankings"][i]}
        det = metrics.row_detail(row, res["tfidf"][i], res["dense"][i], match.confidence)
        assert judge(det, "R1", {"tau": TAU}) == got[key][0][1]
        r1_changed += judge(det, "R1", {"tau": TAU}) != match.confidence(det["rank_tfidf"], det["rank_dense"])
        vd_moved += res["meta"][i]["inferred_role"] is not None
    # 시험이 아무것도 안 하는 경로를 비교하고 있지 않은지: R1 이 등급을 바꾼 행, Veto 가 작동한 행, 사전이 적중한 행이 실제로 있다
    assert r1_changed > 0 and vd_moved > 30 and sum(bool(m["lexicon_hits"]) for m in res["meta"]) > 20


@needs_data
@needs_db
def test_default_app_path_equals_c1_g_d_vd_on_every_dev_v2_row(parity):
    """E4c: 기본 설정(밀집 단독 + 사전 + Vd, R1)으로 저장한 후보를 앱이 보여 주는 방식(동명 접기 앞 3개)대로 접으면
    평가 케이스 C1+G+D+Vd 의 상위 3개와 같고, 1위의 등급도 같다. 저장 후보 20개 밖의 같은 이름 후보 때문에 대표가 달라지는 행은 없다."""
    ci, sid, texts = parity
    assert match.current_settings() == settings("dense")
    with psycopg.connect(ci) as conn:
        match.CACHE.data.clear()
        r = match.match_project(conn, sid, FakeEmbedder())  # 설정 인자 없음 = 앱 기본값
        stored = {}
        for key, ds, conf, name, year, sn in conn.execute(
                "SELECT c.query_key, c.dataset_id, c.confidence, d.name_ko, d.dev_year, d.list_sn FROM match_candidate c JOIN lci_dataset d USING (dataset_id) "
                "WHERE c.run_id = %s ORDER BY c.query_key, c.rank", (r["run_id"],)).fetchall():
            stored.setdefault(key, []).append({"dataset_id": ds, "confidence": conf, "name_ko": name, "year": year, "list_sn": sn})
        conn.commit()
    res = eval_expected(ci, texts, "C1+G+D+Vd")
    for i, text in enumerate(texts):
        key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        shown = match.fold(stored[key], {})
        order = [d for d, _ in res["rankings"][i][:3]]
        assert [c["dataset_id"] for c in shown] == order, f"접은 상위 3개가 다름: {text!r}"
        t_pos = {d: (rk, s) for rk, (d, s) in enumerate(res["tfidf"][i], 1)}
        d_pos = {d: (rk, s) for rk, (d, s) in enumerate(res["dense"][i], 1)}
        (rt, _), (rd, sd) = t_pos.get(order[0], (None, None)), d_pos.get(order[0], (None, None))
        assert shown[0]["confidence"] == judge({"rank_tfidf": rt, "rank_dense": rd, "score_dense": sd}, "R1", {"tau": TAU}), f"1위 등급이 다름: {text!r}"


@needs_data
@needs_db
def test_vd_changes_the_app_result_compared_with_no_veto(parity):
    """Vd 가 실제로 후보 순서를 바꾼다(위 같은-결과 시험이 Vd 를 건너뛴 경로를 비교하는 것이 아님을 확인)."""
    ci, sid, texts = parity
    with_vd = app_candidates(ci, sid, settings(veto="Vd"))
    without = app_candidates(ci, sid, settings(veto=None))
    assert sum([d for d, _ in with_vd[k]] != [d for d, _ in without[k]] for k in with_vd) > 5
