"""인덱서 시험. 임시 DB(lci_test_*)와 가짜 임베더만 쓴다(Ollama 호출 없음)."""
import hashlib
import math

import httpx
import psycopg
import pytest

from app import embedder
from app.db.migrate import migrate
from app.embedder import OLLAMA_DOWN, OllamaEmbedder
from app.indexer import build_index, search_text, text_hash
from test_migrate import needs_db, tempdb  # noqa: F401  (fixture 재사용)

K = "환경부(한국환경산업기술원)"
ROWS = [  # sn, 국문명, 영문명, 분류
    (1, "냉연강판", "Cold rolled steel sheet", "금속"),
    (2, "냉연강판", "Cold rolled steel sheet", "금속"),  # 1과 같은 텍스트
    (3, "열연강판", "Hot rolled steel sheet", "금속"),
    (4, "폴리프로필렌", "Polypropylene", "화학물질"),
    (5, "경유", None, "연료"),  # 영문명 없음
]


class FakeEmbedder:
    """글자 2-gram 을 1024칸에 해시해 만든 결정적 벡터(길이 1). 호출한 텍스트를 기록한다."""

    def __init__(self, dim=1024, model_name="fake:test"):
        self.dim, self.model_name, self.calls = dim, model_name, []

    def embed(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            v = [0.0] * self.dim
            s = t.lower()
            for i in range(len(s) - 1):
                v[int(hashlib.md5(s[i:i + 2].encode()).hexdigest(), 16) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def seed(ci, rows=ROWS):
    with psycopg.connect(ci) as conn:
        for sn, ko, en, cat in rows:
            conn.execute("INSERT INTO lci_dataset (dataset_id, list_sn, name_ko, name_en, category, developer) VALUES (%s,%s,%s,%s,%s,%s)",
                         (f"list-{sn}", sn, ko, en, cat, K))


def count(ci, table, where=""):
    with psycopg.connect(ci) as conn:
        return conn.execute(f"SELECT count(*) FROM {table} {where}").fetchone()[0]


@pytest.fixture
def db(tempdb):  # noqa: F811
    migrate(tempdb)
    seed(tempdb)
    return tempdb


def quiet(*_):
    pass


def test_search_text_and_hash():
    assert search_text("냉연강판", "Cold rolled steel sheet", "금속") == "냉연강판 | Cold rolled steel sheet | 금속"
    assert search_text("경유", None, "연료") == "경유 | 연료"  # 빈 칸 흔적 없음
    assert search_text("경유", "  ", "연료") == "경유 | 연료"
    assert text_hash("경유 | 연료") == hashlib.sha256("경유 | 연료".encode("utf-8")).hexdigest()
    assert len(text_hash("a")) == 64


@needs_db
def test_build_reuses_embeddings(db):
    emb = FakeEmbedder()
    s = build_index(db, emb, activate=True, log=quiet)
    assert (s["datasets"], s["distinct_texts"], s["embedded_new"], s["reused"]) == (5, 4, 4, 0)
    assert count(db, "text_embedding") == 4 and count(db, "index_version_item") == 5
    seed(db, [(6, "LNG", "LNG", "연료")])  # 데이터셋 하나 추가 → 새 텍스트 하나만 임베딩
    s2 = build_index(db, emb, activate=True, log=quiet)
    assert (s2["distinct_texts"], s2["embedded_new"], s2["reused"]) == (5, 1, 4)
    assert emb.calls[-1] == ["LNG | LNG | 연료"]
    with psycopg.connect(db) as conn:
        stats = conn.execute("SELECT stats FROM index_version WHERE version_id = %s", (s2["version_id"],)).fetchone()[0]
        assert set(stats) >= {"datasets", "distinct_texts", "embedded_new", "reused", "seconds", "model", "dim"}
        assert conn.execute("SELECT vector_dims(vector) FROM text_embedding LIMIT 1").fetchone()[0] == 1024


@needs_db
def test_rerun_without_changes(db):
    first = build_index(db, FakeEmbedder(), activate=True, log=quiet)
    again = build_index(db, FakeEmbedder(), activate=True, log=quiet)
    assert again == {"unchanged": True, "version_id": first["version_id"], "datasets": 5}
    assert count(db, "index_version") == 1


@needs_db
def test_dry_run_leaves_nothing(db):
    s = build_index(db, FakeEmbedder(), activate=True, dry_run=True, log=quiet)
    assert s["embedded_new"] == 4
    assert count(db, "text_embedding") == 0 and count(db, "index_version") == 0 and count(db, "index_version_item") == 0


@needs_db
def test_dimension_mismatch_stops_without_trace(db):
    with pytest.raises(SystemExit, match="차원"):
        build_index(db, FakeEmbedder(dim=768), activate=True, log=quiet)
    assert count(db, "text_embedding") == 0 and count(db, "index_version") == 0


@needs_db
def test_activate_switches_to_single_active(db):
    first = build_index(db, FakeEmbedder(), activate=True, log=quiet)
    seed(db, [(6, "LNG", "LNG", "연료")])
    second = build_index(db, FakeEmbedder(), activate=True, log=quiet)
    assert first["version_id"] != second["version_id"]
    with psycopg.connect(db) as conn:
        assert conn.execute("SELECT version_id FROM index_version WHERE active").fetchall() == [(second["version_id"],)]
    seed(db, [(7, "등유", "Kerosene", "연료")])
    third = build_index(db, FakeEmbedder(), log=quiet)  # --activate 없이: 저장만, 활성은 그대로
    with psycopg.connect(db) as conn:
        assert conn.execute("SELECT version_id FROM index_version WHERE active").fetchall() == [(second["version_id"],)]
        assert conn.execute("SELECT active FROM index_version WHERE version_id = %s", (third["version_id"],)).fetchone()[0] is False


def test_ollama_request_shape_and_normalization():
    seen = []

    def handler(request):
        body = __import__("json").loads(request.content)
        seen.append((request.url.path, body["model"], len(body["input"])))
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0] + [0.0] * 1022 for _ in body["input"]]})
    emb = OllamaEmbedder(transport=httpx.MockTransport(handler))
    vectors = emb.embed([f"t{i}" for i in range(40)])
    assert emb.model_name == "ollama:bge-m3"
    assert seen == [("/api/embed", "bge-m3", 32), ("/api/embed", "bge-m3", 8)]  # 배치 32
    assert len(vectors) == 40 and vectors[0][:2] == [0.6, 0.8]  # 길이 1로 정규화


def test_ollama_wrong_dimension_stops():
    emb = OllamaEmbedder(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"embeddings": [[1.0] * 768]})))
    with pytest.raises(SystemExit, match="768"):
        emb.embed(["x"])


def test_ollama_connection_failure_message(monkeypatch):
    monkeypatch.setattr(embedder, "RETRY_DELAYS", (0, 0))

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    emb = OllamaEmbedder(transport=httpx.MockTransport(refuse))
    with pytest.raises(SystemExit) as e:
        emb.embed(["x"])
    assert str(e.value) == OLLAMA_DOWN


def flaky(errors):
    """앞의 errors 개 요청은 그 예외로 실패하고, 그 뒤는 성공하는 가짜 전송. 호출 수를 센다."""
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]("boom", request=request)
        return httpx.Response(200, json={"embeddings": [[1.0] + [0.0] * 1023]})
    return httpx.MockTransport(handler), calls


def test_ollama_retries_once_dropped_connection(monkeypatch):
    slept = []
    monkeypatch.setattr(embedder.time, "sleep", slept.append)
    transport, calls = flaky([httpx.RemoteProtocolError])
    assert OllamaEmbedder(transport=transport).embed(["x"])[0][0] == 1.0
    assert (len(calls), slept) == (2, [1])


def test_ollama_gives_up_after_three_drops(monkeypatch):
    slept = []
    monkeypatch.setattr(embedder.time, "sleep", slept.append)
    transport, calls = flaky([httpx.ReadError, httpx.ConnectError, httpx.ReadError])
    with pytest.raises(SystemExit) as e:
        OllamaEmbedder(transport=transport).embed(["x"])
    assert str(e.value) == OLLAMA_DOWN and (len(calls), slept) == (3, [1, 3])


@pytest.mark.parametrize("fail", ["model_missing", "timeout"])
def test_ollama_no_retry_on_response_error_or_timeout(monkeypatch, fail):
    slept, calls = [], []
    monkeypatch.setattr(embedder.time, "sleep", slept.append)

    def handler(request):
        calls.append(1)
        if fail == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(404, json={"error": "model 'bge-m3' not found"})
    with pytest.raises(SystemExit, match="Ollama"):
        OllamaEmbedder(transport=httpx.MockTransport(handler)).embed(["x"])
    assert (len(calls), slept) == (1, [])
