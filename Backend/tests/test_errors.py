"""공통 오류 형식(A1 #2): 422·500 도 {detail, code, meta}. DB 없이 작은 앱과 실제 앱의 DB 없는 경로로 확인한다."""
import logging

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app import errors
from app.schemas import ErrorBody
from main import app as real_app


def mini():
    app = FastAPI()
    errors.install(app)

    @app.get("/n")
    def n(limit: int = Query(1, ge=1, le=5)):
        return {"limit": limit}

    @app.get("/boom")
    def boom():
        raise RuntimeError("비밀 내부 메시지 postgres://user:pw@127.0.0.1")
    return TestClient(app, raise_server_exceptions=False)


def test_validation_error_uses_common_shape_without_input_echo():
    r = mini().get("/n", params={"limit": "abc"})
    assert r.status_code == 422
    body = r.json()
    ErrorBody.model_validate(body)
    assert body["detail"] == "요청 값이 올바르지 않습니다" and body["code"] == "INVALID_REQUEST"
    assert body["meta"]["errors"][0]["loc"] == ["query", "limit"] and isinstance(body["meta"]["errors"][0]["msg"], str)
    assert "abc" not in str(body)  # 입력 원문은 응답에 넣지 않는다


def test_unhandled_exception_is_500_with_fixed_text_and_log_only_original(caplog):
    with caplog.at_level(logging.ERROR, logger="lci.errors"):
        r = mini().get("/boom")
    assert r.status_code == 500 and r.json() == {"detail": "서버에서 처리하지 못했습니다", "code": "INTERNAL_ERROR"}
    assert "비밀 내부 메시지" not in r.text and "127.0.0.1" not in r.text
    assert any("RuntimeError" in (rec.exc_text or "") or rec.exc_info for rec in caplog.records) and "비밀 내부 메시지" in caplog.text


def test_real_app_validation_error_without_db():
    r = TestClient(real_app).post("/api/sessions/preview")  # 파일 없음 → FastAPI 검증 오류
    assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST" and isinstance(r.json()["detail"], str)
