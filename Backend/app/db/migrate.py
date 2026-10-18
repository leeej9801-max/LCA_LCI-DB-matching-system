"""Backend/db/migrations/*.sql 을 번호 순서로 적용한다. 실행: uv run --env-file ../.env python -m app.db.migrate [--status]"""
import hashlib
import re
import sys
from pathlib import Path

import psycopg

from app.db.connection import conninfo

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migration (
    filename   text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def load_migrations(directory: Path) -> list[tuple[str, bytes]]:
    """(파일명, 내용) 목록. 번호·ASCII 검사는 DB에 닿기 전에 전부 끝낸다."""
    files = sorted(Path(directory).glob("*.sql"))
    numbers = []
    for f in files:
        m = re.match(r"(\d{4})_.+\.sql$", f.name)
        if not m:
            raise SystemExit(f"마이그레이션 파일 이름이 '0001_이름.sql' 형식이 아닙니다: {f.name}")
        numbers.append(int(m[1]))
    if numbers != list(range(1, len(numbers) + 1)):
        raise SystemExit(f"마이그레이션 번호가 1부터 빠짐없이 이어져야 합니다(중복 포함): {numbers}")

    result = []
    for f in files:
        data = f.read_bytes()
        for n, line in enumerate(data.split(b"\n"), 1):
            if any(b > 127 for b in line):
                raise SystemExit(f"{f.name} {n}번째 줄에 ASCII가 아닌 글자가 있습니다. 마이그레이션 파일은 ASCII만 허용합니다")
        result.append((f.name, data))
    return result


def _applied(conn) -> dict[str, str]:
    if conn.execute("SELECT to_regclass('schema_migration')").fetchone()[0] is None:
        return {}
    return dict(conn.execute("SELECT filename, checksum FROM schema_migration").fetchall())


def status(conninfo_: str, directory: Path = MIGRATIONS) -> list[tuple[str, str]]:
    """파일별 applied/pending. DB를 바꾸지 않는다(기록 표도 만들지 않는다)."""
    files = load_migrations(directory)
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        done = _applied(conn)
    return [(name, "applied" if name in done else "pending") for name, _ in files]


def migrate(conninfo_: str, directory: Path = MIGRATIONS) -> tuple[int, int]:
    """새 파일을 적용하고 (적용 수, 건너뜀 수)를 돌려준다."""
    files = load_migrations(directory)
    applied = skipped = 0
    with psycopg.connect(conninfo_, autocommit=True) as conn:
        conn.execute(CREATE_TABLE)
        done = _applied(conn)
        for name, data in files:
            checksum = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()  # 줄바꿈(CRLF/LF)이 달라도 같은 파일
            if name in done:
                if done[name] != checksum:
                    raise SystemExit(f"이미 적용된 {name}이 바뀌었습니다. 새 번호로 추가하세요")
                skipped += 1
                continue
            try:
                conn.execute(data.decode("ascii"))  # 파일이 BEGIN ... COMMIT 을 가지고 있다
            except psycopg.Error as e:
                raise SystemExit(f"{name} 적용 실패: {e}") from e
            conn.execute("INSERT INTO schema_migration (filename, checksum) VALUES (%s, %s)", (name, checksum))
            applied += 1
    return applied, skipped


def main(argv: list[str]) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if "--status" in argv:
            for name, state in status(conninfo()):
                print(f"{state:8} {name}")
        else:
            applied, skipped = migrate(conninfo())
            print(f"적용 {applied}개, 건너뜀 {skipped}개")
    except psycopg.OperationalError as e:
        raise SystemExit(f"DB에 접속하지 못했습니다: {e}") from e


if __name__ == "__main__":
    main(sys.argv[1:])
