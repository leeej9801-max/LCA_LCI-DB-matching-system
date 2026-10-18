"""A20·A01·A21·A02·A08 API 시험. 임시 DB + 가짜 임베더, 작업은 run_match_job 을 직접 불러 실행한다."""
import io
import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.embedder import OLLAMA_DOWN
from app.api.sessions import get_db
from app.schemas import JobStatus, PreviewResponse, SessionPayload
from main import app
from test_bom_match import bomdb  # noqa: F401  (fixture 재사용)
from test_indexer import FakeEmbedder
from test_migrate import needs_db, tempdb  # noqa: F401

CSV = "부품명,사양,UOM,소요량\n냉연강판,1.2T,kg,\"1,200\"\n냉연강판,1.2T,kg,3\n볼트,,EA,4\n,,kg,1\n".encode("utf-8")


@pytest.fixture
def client(bomdb):  # noqa: F811
    def override():
        with psycopg.connect(bomdb) as conn:
            yield conn
    app.dependency_overrides[get_db] = override
    c = TestClient(app)  # with 없이: lifespan(실제 작업자)을 띄우지 않는다
    c.ci = bomdb
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def post(client, url, data=CSV, name="bom.csv", mapping=None):
    return client.post(url, files={"file": (name, io.BytesIO(data), "text/csv")}, data={"mapping": mapping} if mapping else None)


def assert_error(r, status, code, meta=None):
    body = r.json()
    assert r.status_code == status and set(body) <= {"detail", "code", "meta"} and isinstance(body["detail"], str)
    assert body["code"] == code
    if meta is not None:
        assert body["meta"] == meta


@needs_db
def test_preview(client):
    r = post(client, "/api/sessions/preview")
    assert r.status_code == 200
    body = PreviewResponse.model_validate(r.json())
    assert body.rows_total == 4 and body.file_columns == ["부품명", "사양", "UOM", "소요량"]
    assert body.preview_rows[0] == ["냉연강판", "1.2T", "kg", "1,200"]
    assert {m.field: (m.source, m.method) for m in body.column_mapping}["수량"] == ("소요량", "auto")
    r = post(client, "/api/sessions/preview", "품명\nA\n".encode())  # 필수 누락은 오류가 아니라 missing
    assert r.status_code == 200 and {m["field"]: m["method"] for m in r.json()["column_mapping"]}["수량"] == "missing"
    with psycopg.connect(client.ci) as conn:
        assert conn.execute("SELECT count(*) FROM bom_project").fetchone()[0] == 0  # DB 쓰기 없음


@needs_db
def test_upload_errors(client):
    assert_error(post(client, "/api/sessions", "품명\nA\n".encode()), 400, "MISSING_COLUMN", {"missing": ["단위", "수량"]})
    assert_error(post(client, "/api/sessions", mapping='{"품명": "없음"}'), 400, "UNKNOWN_COLUMN", {"columns": ["없음"]})
    assert_error(post(client, "/api/sessions", mapping="{bad"), 400, "INVALID_MAPPING")
    assert_error(post(client, "/api/sessions/preview", name="a.pdf"), 400, "UNREADABLE_FILE")
    assert_error(post(client, "/api/sessions", b"x" * (5 * 1024 * 1024 + 1)), 413, "FILE_TOO_LARGE")
    r = post(client, "/api/sessions", ("품명,단위,수량\n" + "a,kg,1\n" * 2001).encode())
    assert_error(r, 400, "TOO_MANY_ROWS", {"rows": 2001, "limit": 2000})
    assert "code" not in client.get("/api/datasets/list-99999").json()  # A06 404 본문은 그대로(회귀 방지)


@needs_db
def test_upload_job_and_session(client, monkeypatch):
    r = post(client, "/api/sessions")
    assert r.status_code == 202
    sid, jid = r.json()["session_id"], r.json()["job_id"]
    assert len(sid) == 12 and sid.isalnum()
    j = client.get(f"/api/jobs/{jid}").json()
    JobStatus.model_validate(j)
    assert j["state"] == "queued" and j["queued_position"] == 1 and j["result"] == {"session_id": None, "report_id": None}
    assert_error(client.get(f"/api/sessions/{sid}"), 409, "JOB_NOT_FINISHED", {"job_id": jid})
    jobs.claim(client.ci)
    jobs.run_match_job(client.ci, jid, lambda ci: FakeEmbedder())
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["state"] == "succeeded" and j["result"]["session_id"] == sid and "queries" not in j["result"]
    s = client.get(f"/api/sessions/{sid}")
    assert s.status_code == 200
    payload = SessionPayload.model_validate(s.json())
    assert payload.column_mapping is None and payload.db_note == "국가 LCI DB 26건(공개 목록 기준)"
    rows = s.json()["rows"]
    assert [r["source_row"] for r in rows] == [2, 3, 4, 5] and rows[0]["clean"]["quantity"] == 1200.0
    assert rows[1]["issues"] == ["중복 행(원본 2행과 같음)"]
    assert rows[3]["target"] == {"status": "제외", "reason": "품명 없음"} and rows[3]["match_state"] == "no_answer"
    sm = s.json()["summary"]
    assert (sm["total"], sm["target"], sm["exclude"], sm["review"]["pending"], sm["review"]["excluded"], sm["match"]["no_answer"]) == (
        4, 3, 1, 3, 1, 1)
    assert sm["needs_review"] == 3 and sm["match"]["vetoed"] == 0
    assert sm["needs_info"] == 1 and rows[2]["conversion"]["missing"] == ["개당 중량"]  # 볼트 EA ← 기본 선택(kg 데이터셋)


@needs_db
def test_not_found(client):
    assert_error(client.get("/api/jobs/job-nope"), 404, "JOB_NOT_FOUND")
    assert_error(client.get("/api/sessions/abcdefabcdef"), 404, "SESSION_NOT_FOUND")


@needs_db
def test_sample_csv_round_trips(client):
    r = client.get("/api/sample.csv")
    assert r.status_code == 200 and r.content.startswith("\ufeff".encode("utf-8"))
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "품명,규격,단위,수량" and len(lines) == 13
    p = post(client, "/api/sessions/preview", r.content, "sample.csv")
    assert p.status_code == 200 and p.json()["rows_total"] == 12
    assert json.loads(json.dumps(p.json()))["column_mapping"][0]["sample"] == "SGCC 용융아연도금강판"


@needs_db
def test_failed_job_gives_job_failed_not_job_not_finished(client):
    class Down(FakeEmbedder):
        def embed(self, texts):
            raise SystemExit(OLLAMA_DOWN)
    r = post(client, "/api/sessions", "품명,단위,수량\n새 부품 가나다,kg,1\n".encode())
    sid, jid = r.json()["session_id"], r.json()["job_id"]
    assert_error(client.get(f"/api/sessions/{sid}"), 409, "JOB_NOT_FINISHED", {"job_id": jid})  # 아직 대기 중
    jobs.claim(client.ci)
    jobs.run_match_job(client.ci, jid, lambda ci: Down())
    got = client.get(f"/api/sessions/{sid}")
    assert_error(got, 409, "JOB_FAILED", {"job_id": jid, "error_code": "EMBEDDER_UNAVAILABLE"})
    assert got.json()["detail"] == f"매칭 작업이 실패했습니다: {OLLAMA_DOWN}"
