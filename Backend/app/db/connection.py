import os

from psycopg.conninfo import make_conninfo


def conninfo() -> str:
    """환경변수로 만든 접속 문자열. 비밀번호는 로그·예외 메시지에 넣지 않는다."""
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD가 없습니다. .env를 확인하세요")
    return make_conninfo(
        # localhost 는 Windows 에서 IPv6(::1)를 먼저 시도해 접속마다 8초 걸린다. compose 는 127.0.0.1 에만 연다
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "lci"),
        user=os.environ.get("POSTGRES_USER", "lci"),
        password=password,
    )
