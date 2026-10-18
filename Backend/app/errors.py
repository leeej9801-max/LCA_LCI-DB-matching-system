"""공통 오류 형식(스펙 07): 본문은 {detail, code?, meta?} 한 가지 모양. code·meta 는 없으면 키를 뺀다."""
from fastapi import Request
from fastapi.responses import JSONResponse


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


def install(app):
    app.add_exception_handler(ApiError, api_error_handler)
