"""매칭 시험. 임시 DB + 가짜 임베더(네트워크 없음)."""
import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.bom import match
from app.bom.clean import clean_rows
from app.db.migrate import migrate
from app.indexer import build_index
from test_indexer import FakeEmbedder, quiet
from test_migrate import needs_db, tempdb  # noqa: F401  (fixture 재사용)

K = "환경부(한국환경산업기술원)"
DATASETS = [  # sn, 국문명, 영문명, 분류, 연도 — 동명 냉연강판 3건(연도 다름)
    (1, "냉연강판", "Cold rolled steel sheet", "금속", 2005),
    (2, "냉연강판", "Cold rolled steel sheet", "금속", 2022),
    (3, "냉연강판", "Cold rolled steel sheet", "금속", 2003),
    (4, "열연강판", "Hot rolled steel sheet", "금속", 2022),
] + [(n, f"데이터셋{n}", f"Dataset {n}", "화학물질", 2020) for n in range(5, 27)]


def seed_datasets(ci, rows=DATASETS):
    with psycopg.connect(ci) as conn:
        for sn, ko, en, cat, year in rows:
            conn.execute("INSERT INTO lci_dataset (dataset_id, list_sn, name_ko, name_en, category, developer, dev_year, version, ref_flow_unit) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (f"list-{sn}", sn, ko, en, cat, K, year, "1.0.0" if sn != 3 else "-",
                                                                  "kg" if sn != 4 else None))


def add_session(ci, rows, session_id="abcdefABCDEF"):
    items = clean_rows([{"source_row": i + 2, "name": n, "spec": "", "unit": "kg", "quantity": "1"} for i, n in enumerate(rows)])
    with psycopg.connect(ci) as conn:
        conn.execute("INSERT INTO bom_project (project_id, source_file, expires_at) VALUES (%s, 'a.csv', now() + interval '1 day')",
                     (session_id,))
        for it in items:
            conn.execute("INSERT INTO bom_item (project_id, row_no, source_row, raw_name, raw_spec, raw_unit, raw_qty, clean_name, clean_spec, "
                         "clean_unit, clean_unit_display, clean_qty, norm_text, query_key, issues, target_status, target_reason) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (session_id, it["row_no"], it["source_row"], it["raw_name"], it["raw_spec"], it["raw_unit"], it["raw_qty"],
                          it["clean_name"], it["clean_spec"], it["clean_unit"], it["clean_unit_display"], it["clean_qty"], it["norm_text"],
                          it["query_key"], Jsonb(it["issues"]), it["target_status"], it["target_reason"]))
    return session_id


@pytest.fixture
def bomdb(tempdb):  # noqa: F811
    migrate(tempdb)
    seed_datasets(tempdb)
    build_index(tempdb, FakeEmbedder(), activate=True, log=quiet)
    match.CACHE.data.clear()
    return tempdb


@pytest.mark.parametrize("rt,rd,expected", [
    (1, 1, "높음"), (2, 3, "보통"), (1, 15, "보통"), (None, 1, "보통"), (4, 1, "보통"), (2, 4, "낮음"), (None, None, "낮음"),
])
def test_confidence_rule(rt, rd, expected):
    assert match.confidence(rt, rd) == expected


def test_score01_is_relative_and_clipped():
    assert match.score01(2 / 61) == pytest.approx(1.0) and match.score01(1 / 61) == pytest.approx(0.5) and match.score01(1.0) == 1.0


def cand(name, score, **kw):
    return {"dataset_id": kw.get("ds", name), "name_ko": name, "name_en": "x", "category": "c", "org": "o", "year": kw.get("year", 2020),
            "version": "1.0.0", "reference_unit": "kg", "score_rrf": score, "confidence": "보통", "rank_tfidf": 1, "rank_dense": 2,
            "vetoed": False, "veto_rule_id": None, "has_xml": True, "geography": None, "allocation": None, "cutoff": None, "tech": None,
            "list_sn": kw.get("sn", 1), "role": kw.get("role")}


ITEM = dict(zip(match.ITEM_COLS, (1, 2, None, None, "a", "", "kg", "1", "a", "", "kg", "kg", 1.0, "a", "k", [], "대상", "",
                                   None, None, None, None, None, "pending", "", None)))


def ranked(name, rt, rd, ds=None, score=0.5):
    return cand(name, score, ds=ds or name) | {"rank_tfidf": rt, "rank_dense": rd}


@pytest.mark.parametrize("cands,expected,why", [
    ([ranked("A", 1, 1), ranked("B", 2, 2)], False, "두 방식 1위가 같은 데이터셋"),
    ([ranked("A", 1, 2, ds="a1"), ranked("A", 2, 1, ds="a2")], False, "1위가 같은 이름의 다른 데이터셋(동명)"),
    ([ranked("A", 1, 2), ranked("B", 2, 1)], True, "1위가 서로 다른 이름"),
    ([ranked("A", 1, None), ranked("B", 2, None)], False, "밀집 목록에 후보가 없음"),
    ([ranked("A", None, 1), ranked("B", None, 2)], False, "TF-IDF 목록에 후보가 없음"),
])
def test_ambiguous_rule(cands, expected, why):
    assert match.is_ambiguous(cands) is expected, why
    assert match.row_payload(ITEM, cands, {})["ambiguous"] is expected


def test_high_confidence_is_never_ambiguous():
    # 높음 = 두 목록 모두 같은 데이터셋이 1위 → 이름이 같으므로 ambiguous 가 될 수 없다
    top = ranked("A", 1, 1)
    assert match.confidence(1, 1) == "높음" and match.is_ambiguous([top, ranked("B", 2, 2)]) is False
    for other in (ranked("B", 2, 3), ranked("C", None, 2)):
        assert match.is_ambiguous([top, other]) is False


def test_ambiguous_false_for_no_answer():
    empty = match.row_payload(ITEM, [], {})
    assert (empty["match_state"], empty["candidates"], empty["selected_id"], empty["selected"]) == ("no_answer", [], None, None)


@needs_db
def test_match_dedupes_queries_caches_and_stores_20(bomdb, monkeypatch):
    calls = {"tfidf": 0, "dense": 0}
    real_t, real_d = match.tfidf_rank, match.dense_rank
    monkeypatch.setattr(match, "tfidf_rank", lambda *a, **k: calls.__setitem__("tfidf", calls["tfidf"] + 1) or real_t(*a, **k))
    monkeypatch.setattr(match, "dense_rank", lambda *a, **k: calls.__setitem__("dense", calls["dense"] + 1) or real_d(*a, **k))
    sid = add_session(bomdb, ["냉연강판", "냉연강판", "냉연강판", "열연강판"])  # 같은 자재 3행
    emb = FakeEmbedder()
    progress = []
    with psycopg.connect(bomdb) as conn:
        r = match.match_project(conn, sid, emb, progress=lambda d, t: progress.append((d, t)))
    assert (r["queries"], r["cache_hits"]) == (2, 0) and calls == {"tfidf": 2, "dense": 2} and progress == [(1, 2), (2, 2)]
    assert sum(len(c) for c in emb.calls) == 2
    with psycopg.connect(bomdb) as conn:
        r2 = match.match_project(conn, add_session(bomdb, ["냉연강판"], "zzzzzzzzzzzz"), emb)
        counts = conn.execute("SELECT query_key, count(*) FROM match_candidate WHERE run_id = %s GROUP BY 1", (r["run_id"],)).fetchall()
    assert r2["cache_hits"] == 1 and sum(len(c) for c in emb.calls) == 2  # 두 번째 세션은 캐시 적중, 임베딩 호출 없음
    assert sorted(n for _, n in counts) == [20, 20]  # 질의마다 상위 20


@needs_db
def test_rows_fold_same_name_and_duplicate_group(bomdb):
    sid = add_session(bomdb, ["냉연강판"])
    with psycopg.connect(bomdb) as conn:
        match.match_project(conn, sid, FakeEmbedder())
        [row] = match.build_rows(conn, sid)
    names = [c["name"] for c in row["candidates"]]
    assert len(names) == 3 and len(set(names)) == 3  # 동명 냉연강판 3건이 하나로 접힘
    top = row["candidates"][0]
    assert top["dataset_id"] == "list-2" and top["year"] == 2022  # 대표 = 최신 연도
    assert top["duplicate_group"] == {"size": 3, "others": ["list-1", "list-3"]}
    for c in row["candidates"]:
        if c["dataset_id"] == "list-4":
            assert c["reference_unit"] is None  # 단위가 없는 데이터셋도 null 로 통과(계약 변경)
    assert "이름이 같은 데이터셋 3건 중 최신" in top["reasons"] and "질의와 이름 부분 일치" in top["reasons"]
    assert row["selected_id"] == "list-2" and row["selected"]["manual"] is False and row["match_state"] == "candidate"
    assert (row["synonym_hits"], row["attrs"], row["overrides"], row["explanation"]) == ([], {}, {}, None)
    assert (row["conversion"]["status"], row["conversion"]["method"]) == ("ok", "identity")  # 기본 선택(kg) 기준으로 계산되어 나온다
