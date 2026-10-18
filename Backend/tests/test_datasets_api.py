"""A05·A06 시험. 임시 DB(lci_test_*)에 합성 10행을 넣고 get_conn 의존성을 바꿔 끼운다."""
import json
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.api.datasets import get_conn
from app.db.migrate import migrate
from app.schemas import DatasetDetail, DatasetSearchResponse
from main import app
from test_migrate import needs_db, tempdb  # noqa: F401  (fixture 재사용)

ROOT = Path(__file__).parents[2]
SEARCH_FIXTURE = ROOT / "docs/LCA/fixtures/datasets.search.json"
DETAIL_FIXTURE = ROOT / "Frontend/src/api/mock/data/dataset.detail.json"
K = "환경부(한국환경산업기술원)"

# sn, 국문명, 영문명, 분류, 기관, 연도, 버전, has_xml, 단위, data_type
ROWS = [
    (1, "알루미늄 압출품", "Aluminium extrusion", "금속", K, 2022, "1.0.0", True, "kg", "LCI result"),
    (2, "알루미늄 압출품", "Aluminium extrusion", "금속", "산업통상자원부", 2001, "-", False, None, None),  # 동명, 옛 엑셀
    (3, "알루미늄 압출품", "Aluminium extrusion", "금속", K, 2022, "1.0.0", True, "kg", "LCI result"),  # 동명, 같은 연도 → sn 큰 3이 대표
    (4, "알루미늄", "Aluminium", "금속", K, 2018, "1.0.0", True, "kg", "LCI result"),
    (5, "냉연 알루미늄 판", "Rolled aluminium sheet", "금속", K, 2024, "1.0.0", True, "kg", "LCI result"),
    (6, "폴리프로필렌", "Polypropylene", "화학물질", K, 2024, "1.0.0", True, "kg", "LCI result"),
    (7, "100% 재생 PET", "PET 100% recycled", "화학물질", "환경부", 2012, "-", False, "kg", None),
    (8, "경유", "Diesel", "연료", K, 2022, "1.0.0", False, None, None),
    (9, "가솔린_혼합", "Gasoline blend", "연료", K, 2023, "1.0.0", True, "MJ", "LCI result"),
    (10, "LNG", "LNG", "연료", "산업통상자원부", 2003, "-", False, "kg", None),
]


@pytest.fixture
def client(tempdb):  # noqa: F811
    migrate(tempdb)
    with psycopg.connect(tempdb) as conn:
        for sn, ko, en, cat, org, year, ver, xml, unit, dtype in ROWS:
            conn.execute(
                "INSERT INTO lci_dataset (dataset_id, list_sn, name_ko, name_en, category, developer, dev_year, version, has_xml, "
                "ref_flow_unit, dataset_type, allocation) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (f"list-{sn}", sn, ko, en, cat, org, year, ver, xml, unit, dtype, "Allocation - mass" if xml else None))

    def override():
        with psycopg.connect(tempdb, row_factory=dict_row) as conn:
            yield conn
    app.dependency_overrides[get_conn] = override
    try:
        c = TestClient(app)
        c.conninfo = tempdb  # 시험에서 DB 원문을 직접 확인할 때 쓴다
        yield c
    finally:
        app.dependency_overrides.clear()


def get(client, **params):
    r = client.get("/api/datasets", params=params)
    assert r.status_code == 200, r.text
    DatasetSearchResponse.model_validate(r.json())
    return r.json()


def sns(body):
    return [i["list_row"] for i in body["items"]]


@needs_db
def test_group_total_facets_and_duplicate_count(client):
    body = get(client)
    assert body["total"] == 8  # 10행 중 동명 3행이 1행으로
    rep = next(i for i in body["items"] if i["name"] == "알루미늄 압출품")
    assert rep["list_row"] == 3 and rep["duplicate_count"] == 3  # 연도 같으면 sn 큰 것
    assert sum(body["facets"]["category"].values()) == body["total"]
    # 값마다 "그 값을 고르면 보일 수": XML 3·4·5·6·9 / 엑셀 2·7·8·10. 동명 그룹(1·2·3)은 양쪽에 다 세어 합 9 > total 8
    assert body["facets"]["has_xml"] == {"true": 5, "false": 4}
    flat = get(client, group_duplicates="false")
    assert flat["total"] == 10
    assert next(i for i in flat["items"] if i["list_row"] == 2)["duplicate_count"] == 3


@needs_db
def test_q_partial_match_and_escape(client):
    assert set(sns(get(client, q="알루미늄"))) == {3, 4, 5}
    assert set(sns(get(client, q="ALUMINIUM"))) == {3, 4, 5}  # 대소문자 무시, 영문명
    assert sns(get(client, q="100%")) == [7]  # % 는 글자 그대로
    assert get(client, q="%")["total"] == 1  # '100% 재생 PET' 만
    assert sns(get(client, q="_")) == [9]  # _ 도 글자 그대로
    assert get(client, q="없는이름")["total"] == 0
    assert client.get("/api/datasets", params={"q": "가" * 101}).status_code == 422


@needs_db
def test_filters_do_not_shrink_facets(client):
    all_facets = get(client)["facets"]
    body = get(client, category="연료,화학물질")
    assert set(sns(body)) == {6, 7, 8, 9, 10}
    assert body["facets"]["category"] == all_facets["category"]  # 자기 필터(분류)는 빼고 센다
    assert body["facets"]["has_xml"] == {"true": 2, "false": 3}  # has_xml 은 분류 필터를 따른다(6·9 / 7·8·10)
    assert set(sns(get(client, has_xml="true", category="연료"))) == {9}
    assert set(sns(get(client, has_xml="false"))) == {2, 7, 8, 10}  # 동명 그룹은 필터 뒤에 접어 엑셀 행(2)이 대표


@needs_db
def test_sorts(client):
    assert sns(get(client, sort="year_desc", group_duplicates="false"))[:3] == [6, 5, 9]
    names = [i["name"] for i in get(client, sort="name")["items"]]
    assert names == sorted(names)
    # relevance: 완전 일치(알루미늄) → 시작 일치(알루미늄 압출품) → 부분 일치(냉연 알루미늄 판)
    assert sns(get(client, q="알루미늄", sort="relevance")) == [4, 3, 5]
    assert sns(get(client)) == sns(get(client, sort="year_desc"))  # q 가 없으면 relevance = year_desc


@needs_db
def test_limit_offset(client):
    assert len(get(client, limit=2)["items"]) == 2
    assert sns(get(client, limit=3, offset=3)) == sns(get(client, limit=50))[3:6]
    assert client.get("/api/datasets", params={"limit": 51}).status_code == 422
    assert client.get("/api/datasets", params={"offset": -1}).status_code == 422


@needs_db
def test_detail_nulls_duplicates_and_404(client):
    r = client.get("/api/datasets/list-2")
    assert r.status_code == 200
    d = DatasetDetail.model_validate(r.json()).model_dump()
    assert d["reference_unit"] is None and d["data_type"] is None and d["allocation"] is None and d["tech_summary"] is None
    assert d["duplicate_count"] == 3
    assert [x["dataset_id"] for x in d["duplicates"]] == ["list-3", "list-1"]  # 자기 자신 제외, 연도 내림(같으면 sn 큰 것)
    for bad in ("list-99999", "abc", "list-1x"):
        r = client.get(f"/api/datasets/{bad}")
        assert r.status_code == 404 and isinstance(r.json()["detail"], str)


@needs_db
@pytest.mark.skipif(not SEARCH_FIXTURE.exists(), reason="docs/LCA/fixtures 없음")
def test_keys_match_fixtures(client):
    def keys(path):
        return {k for k in json.loads(path.read_text(encoding="utf-8")) if not k.startswith("_")}
    body = get(client)
    search = json.loads(SEARCH_FIXTURE.read_text(encoding="utf-8"))
    assert set(body) == keys(SEARCH_FIXTURE)
    assert set(body["items"][0]) == set(search["items"][0])
    assert set(body["facets"]) == set(search["facets"])
    assert set(client.get("/api/datasets/list-1").json()) == keys(DETAIL_FIXTURE)


# --- T8.1: facet 은 자기 필터만 빼고, 값마다 "그 값을 고르면 보일 total" ---
@needs_db
@pytest.mark.parametrize("group", ["true", "false"])
@pytest.mark.parametrize("filters", [{}, {"category": "연료"}, {"has_xml": "false"}, {"category": "금속", "has_xml": "false"}])
def test_facets_match_selecting_each_value(client, group, filters):
    q = {"q": "a", "group_duplicates": group}  # 영문명에 a 가 든 행: 1~5(금속, 2만 엑셀), 9(연료)
    body = get(client, **q, **filters)
    for c, n in body["facets"]["category"].items():  # 분류 facet: 분류만 그 값으로 바꾼 total
        assert get(client, **q, **{**filters, "category": c})["total"] == n
    for v, n in body["facets"]["has_xml"].items():  # has_xml facet: has_xml 만 그 값으로 바꾼 total
        assert get(client, **q, **{**filters, "has_xml": v})["total"] == n
    if "category" not in filters:
        assert sum(body["facets"]["category"].values()) == body["total"]  # 분류는 겹치지 않아 합 = total
    if "has_xml" not in filters and group == "false":
        assert sum(body["facets"]["has_xml"].values()) == body["total"]  # 접지 않으면 XML·엑셀도 겹치지 않는다


@needs_db
def test_facets_four_combinations_with_q(client):
    def f(**kw):
        b = get(client, q="알루미늄", **kw)
        return b["total"], b["facets"]
    # q 만: 3(대표)·4·5, 모두 금속·XML. 엑셀 행 2 는 has_xml=false 를 고르면 보인다
    assert f() == (3, {"category": {"금속": 3}, "has_xml": {"true": 3, "false": 1}})
    assert f(category="금속") == (3, {"category": {"금속": 3}, "has_xml": {"true": 3, "false": 1}})
    assert f(has_xml="false") == (1, {"category": {"금속": 1}, "has_xml": {"true": 3, "false": 1}})
    assert f(category="연료", has_xml="false") == (0, {"category": {"금속": 1}, "has_xml": {"true": 0, "false": 0}})


@needs_db
def test_version_dash_is_null(client):
    by = {i["list_row"]: i for i in get(client, group_duplicates="false", limit=50)["items"]}
    assert by[2]["version"] is None and by[7]["version"] is None and by[1]["version"] == "1.0.0"
    d = client.get("/api/datasets/list-1").json()
    assert {x["dataset_id"]: x["version"] for x in d["duplicates"]} == {"list-3": "1.0.0", "list-2": None}
    assert client.get("/api/datasets/list-10").json()["version"] is None
    with psycopg.connect(client.conninfo) as conn:
        assert conn.execute("SELECT version FROM lci_dataset WHERE dataset_id = 'list-2'").fetchone()[0] == "-"  # DB 원문 그대로
