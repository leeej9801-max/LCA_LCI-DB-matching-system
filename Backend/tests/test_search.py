"""검색 시험. 임시 DB와 가짜 임베더(test_indexer.FakeEmbedder)만 쓴다."""
import psycopg
import pytest

from app.db.migrate import migrate
from app.indexer import build_index
from app.search import rrf, search
from test_indexer import FakeEmbedder, quiet, seed
from test_migrate import needs_db, tempdb  # noqa: F401  (fixture 재사용)


def test_rrf_hand_calculation():
    sn = {"a": 1, "b": 2, "c": 3}
    tfidf = [("a", 0.9), ("b", 0.5)]  # a 1위, b 2위
    dense = [("b", 0.8), ("c", 0.7)]  # b 1위, c 2위
    got = dict(rrf([tfidf, dense], sn))
    assert got["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert got["a"] == pytest.approx(1 / 61)  # dense 에 없으니 더하지 않음
    assert got["c"] == pytest.approx(1 / 62)
    assert [d for d, _ in rrf([tfidf, dense], sn)] == ["b", "a", "c"]


def test_rrf_tie_puts_larger_list_sn_first():
    sn = {"x": 10, "y": 20}
    assert [d for d, _ in rrf([[("x", 1.0)], [("y", 1.0)]], sn)] == ["y", "x"]  # 둘 다 1/61


@pytest.fixture
def indexed(tempdb):  # noqa: F811
    migrate(tempdb)
    seed(tempdb)
    build_index(tempdb, FakeEmbedder(), activate=True, log=quiet)
    return tempdb


@needs_db
def test_search_returns_both_rankings(indexed):
    with psycopg.connect(indexed) as conn:
        version, results = search(conn, FakeEmbedder(), "냉연강판", k=3)
    assert version.startswith("idx-")
    top = results[0]
    assert top["dataset_id"] in ("list-1", "list-2") and top["tfidf"] and top["dense"]
    assert [r["dataset_id"] for r in results[:2]] == ["list-2", "list-1"]  # 같은 텍스트 동점 → list_sn 큰 것이 앞, 합치지 않음
    assert results[0]["rrf"] == pytest.approx(2 / 61)


@needs_db
def test_stale_index_is_detected(indexed):
    with psycopg.connect(indexed) as conn:
        conn.execute("UPDATE lci_dataset SET name_ko = '냉연강판(수정)' WHERE dataset_id = 'list-1'")
    with psycopg.connect(indexed) as conn, pytest.raises(SystemExit, match="인덱스가 오래됨"):
        search(conn, FakeEmbedder(), "냉연강판")


@needs_db
def test_new_dataset_not_in_index_is_stale(indexed):
    seed(indexed, [(9, "새 데이터셋", "New", "금속")])
    with psycopg.connect(indexed) as conn, pytest.raises(SystemExit, match="인덱스가 오래됨"):
        search(conn, FakeEmbedder(), "냉연강판")


@needs_db
def test_model_mismatch_stops(indexed):
    with psycopg.connect(indexed) as conn, pytest.raises(SystemExit, match="모델"):
        search(conn, FakeEmbedder(model_name="fake:other"), "냉연강판")
