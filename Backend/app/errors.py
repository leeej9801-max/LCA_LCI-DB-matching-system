"""공통 오류 형식(스펙 07): 본문은 {detail, code?, meta?} 한 가지 모양. code·meta 는 없으면 키를 뺀다."""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("lci.errors")


class ApiError(Exception):
    def __init__(self, status, detail, code=None, meta=None):
        super().__init__(detail)
        self.status, self.detail, self.code, self.meta = status, detail, code, meta


async def api_error_handler(request: Request, exc: ApiError):
    body = {"detail": exc.detail}
    if exc.code:
        body["code"] = exc.code
    if exc.meta is not None:
        body["meta"] = exc.meta
    return JSONResponse(body, status_code=exc.status)


async def validation_error_handler(request: Request, exc: RequestValidationError):
    """FastAPI 기본 422(detail 이 배열)를 공통 모양으로. 입력값 원문은 응답에 넣지 않는다(loc·msg 만)."""
    errors = [{"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", "")} for e in exc.errors()]
    return JSONResponse({"detail": "요청 값이 올바르지 않습니다", "code": "INVALID_REQUEST", "meta": {"errors": errors}}, status_code=422)


async def unhandled_error_handler(request: Request, exc: Exception):
    """처리 안 된 예외: 응답에는 고정 문장만, 원문(예외·스택)은 서버 로그에만."""
    log.error("처리하지 못한 예외: %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse({"detail": "서버에서 처리하지 못했습니다", "code": "INTERNAL_ERROR"}, status_code=500)


def install(app):
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
