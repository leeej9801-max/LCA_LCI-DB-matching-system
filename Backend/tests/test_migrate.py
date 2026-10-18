"""마이그레이션 적용 스크립트 시험. DB에 닿는 시험은 임시 데이터베이스(lci_test_*)에서만 하고, 기본 lci DB는 건드리지 않는다."""
import os
import re
import secrets
import shutil
from pathlib import Path

import psycopg
import pytest
from psycopg import errors
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.db.connection import conninfo
from app.db.migrate import MIGRATIONS, migrate, status

ENV_FILE = Path(__file__).parents[2] / ".env"


def _load_env():
    """`uv run pytest`만 쳐도 되도록 .env 의 POSTGRES_* 를 읽는다(이미 있는 환경변수가 우선)."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().startswith("POSTGRES_"):
            os.environ.setdefault(key.strip(), value.strip())


def _admin_conninfo():
    return make_conninfo(conninfo(), dbname="postgres")


def _db_up():
    _load_env()
    try:
        with psycopg.connect(_admin_conninfo(), connect_timeout=3):
            return True
    except (psycopg.Error, RuntimeError):
        return False


needs_db = pytest.mark.skipif(not _db_up(), reason="DB가 켜져 있지 않음")


@pytest.fixture
def tempdb(monkeypatch):
    """lci_test_<무작위> 데이터베이스의 접속 문자열. 시험이 끝나면 지운다.
    비밀번호는 접속 문자열에 넣지 않고 PGPASSWORD 로 넘긴다(실패 출력에 접속 문자열이 찍혀도 비밀번호가 보이지 않게)."""
    params = conninfo_to_dict(conninfo())
    monkeypatch.setenv("PGPASSWORD", params.pop("password"))
    name = f"lci_test_{secrets.token_hex(4)}"
    with psycopg.connect(_admin_conninfo(), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            yield make_conninfo(**params | {"dbname": name})
        finally:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


# 저장소의 마이그레이션 파일 수는 늘어난다. 시험용 새 파일은 그다음 번호로 만든다
FILES = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
N = len(FILES)
NEXT = f"{N + 1:04d}"


def copy_migrations(tmp_path):
    dest = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, dest)
    return dest


@needs_db
def test_apply_from_scratch(tempdb):
    assert migrate(tempdb) == (N, 0)
    with psycopg.connect(tempdb) as conn:
        for table in ("lci_dataset", "index_version", "index_version_item", "text_embedding", "job", "schema_migration"):
            assert conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None, table


@needs_db
def test_apply_twice(tempdb):
    migrate(tempdb)
    assert migrate(tempdb) == (0, N)


@needs_db
def test_status_does_not_create_table(tempdb):
    assert status(tempdb) == [(f, "pending") for f in FILES]
    with psycopg.connect(tempdb) as conn:
        assert conn.execute("SELECT to_regclass('schema_migration')").fetchone()[0] is None
    migrate(tempdb)
    assert status(tempdb) == [(f, "applied") for f in FILES]


@needs_db
def test_changed_file_aborts(tempdb, tmp_path):
    directory = copy_migrations(tmp_path)
    migrate(tempdb, directory)
    with open(directory / "0001_data_index_job.sql", "a", encoding="ascii") as f:
        f.write("\n-- changed\n")
    with pytest.raises(SystemExit, match="바뀌었습니다"):
        migrate(tempdb, directory)


@needs_db
def test_crlf_does_not_change_checksum(tempdb, tmp_path):
    directory = copy_migrations(tmp_path)
    migrate(tempdb, directory)
    f = directory / "0001_data_index_job.sql"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert migrate(tempdb, directory) == (0, N)


@needs_db
def test_failed_file_rolls_back_then_retry_succeeds(tempdb, tmp_path):
    directory = copy_migrations(tmp_path)
    bad = directory / f"{NEXT}_bad.sql"
    bad.write_text("BEGIN; CREATE TABLE t_bad (id int); SELECT 1/0; COMMIT;\n", encoding="ascii")
    with pytest.raises(SystemExit, match=re.escape(f"{NEXT}_bad.sql 적용 실패")):
        migrate(tempdb, directory)
    with psycopg.connect(tempdb) as conn:
        assert conn.execute("SELECT count(*) FROM schema_migration WHERE filename = %s", (bad.name,)).fetchone()[0] == 0
        assert conn.execute("SELECT to_regclass('t_bad')").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM schema_migration").fetchone()[0] == N  # 앞 파일들은 적용된 채 남는다
    bad.write_text("BEGIN; CREATE TABLE t_bad (id int); COMMIT;\n", encoding="ascii")
    assert migrate(tempdb, directory) == (1, N)


@needs_db
def test_non_ascii_aborts_before_applying(tempdb, tmp_path):
    directory = copy_migrations(tmp_path)
    (directory / f"{NEXT}_extra.sql").write_text("-- 한글\nSELECT 1;\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=re.escape(f"{NEXT}_extra.sql 1번째 줄")):
        migrate(tempdb, directory)
    with psycopg.connect(tempdb) as conn:  # 0001도 적용되지 않았다
        assert conn.execute("SELECT to_regclass('schema_migration')").fetchone()[0] is None


@pytest.mark.parametrize("names", [["0001_a.sql", "0003_c.sql"], ["0001_a.sql", "0001_b.sql"]])
def test_numbering_gap_or_duplicate_aborts(tmp_path, names):
    for n in names:
        (tmp_path / n).write_text("SELECT 1;\n", encoding="ascii")
    with pytest.raises(SystemExit, match="번호"):
        status("unused", tmp_path)  # 번호 검사는 DB에 닿기 전에 끝난다


@needs_db
def test_vector_roundtrip(tempdb):
    migrate(tempdb)
    a = [0.0] * 1024
    a[0] = 1.0
    b = [0.0] * 1024
    b[1] = 1.0
    vec = lambda v: "[" + ",".join(map(str, v)) + "]"  # noqa: E731
    with psycopg.connect(tempdb, autocommit=True) as conn:
        for h, v in (("a", a), ("b", b)):
            conn.execute("INSERT INTO text_embedding (text_hash, model_name, vector) VALUES (%s, 'm', %s::vector)", (h, vec(v)))
        row = conn.execute("SELECT text_hash FROM text_embedding ORDER BY vector <=> %s::vector LIMIT 1", (vec(b),)).fetchone()
    assert row[0] == "b"


@needs_db
def test_constraints(tempdb):
    migrate(tempdb)
    with psycopg.connect(tempdb, autocommit=True) as conn:
        with pytest.raises(errors.CheckViolation):
            conn.execute("INSERT INTO lci_dataset (dataset_id, list_sn, name_ko, category) VALUES ('list-5', 6, 'x', 'y')")
        conn.execute("INSERT INTO index_version (version_id, model_name, active) VALUES ('v1', 'm', true)")
        with pytest.raises(errors.UniqueViolation):
            conn.execute("INSERT INTO index_version (version_id, model_name, active) VALUES ('v2', 'm', true)")
        with pytest.raises(errors.CheckViolation):
            conn.execute("INSERT INTO job (job_id, kind, state) VALUES ('j1', 'match', 'weird')")
