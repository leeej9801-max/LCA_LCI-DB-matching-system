"""정답셋 검증·적재와 마이그레이션 0003 제약 시험. 임시 DB(lci_test_*)만 쓴다."""
import csv

import psycopg
import pytest
from psycopg import errors

from app.db.migrate import migrate
from app.evaluation.gold import COLUMNS, assign_splits, load, read_csv, validate
from app.indexer import build_index
from test_indexer import FakeEmbedder, quiet, seed
from test_migrate import needs_db, tempdb  # noqa: F401  (fixture 재사용)

DATASETS = [  # sn, 국문명, 영문명, 분류 — 동명 1·2 포함 10행
    (1, "냉연강판", "Cold rolled steel sheet", "금속"),
    (2, "냉연강판", "Cold rolled steel sheet", "금속"),
    (3, "열연강판", "Hot rolled steel sheet", "금속"),
    (4, "폴리프로필렌", "Polypropylene", "화학물질"),
    (5, "경유", "Diesel", "연료"),
    (6, "알루미늄 압출품", "Aluminium extrusion", "금속"),
    (7, "알루미늄 판", "Aluminium sheet", "금속"),
    (8, "전기", "Electricity", "전기"),
    (9, "LNG", "LNG", "연료"),
    (10, "용융아연도금강판", "Hot-dip galvanized steel", "금속"),
]
# bom_text, expected, is_no_match, hard_pair_group, input_style, label_source, split
GOLD = [
    ("냉연강판 SPCC", "list-1", "0", "cold-hot", "약어", "pool", ""),
    ("열연 강판", "list-3", "0", "cold-hot", "띄어쓰기", "pool", ""),
    ("cold rolled steel", "list-2", "0", "", "영문", "manual", ""),
    ("폴리프로필랜", "list-4", "0", "", "오타", "pool", ""),
    ("diesel oil", "list-5", "0", "", "영문", "pool", ""),
    ("알루미늄압출", "list-6", "0", "al", "띄어쓰기", "pool", ""),
    ("알루미늄 판재", "list-7", "0", "al", "약어", "pool", ""),
    ("전기 사용량", "list-8", "0", "", "약어", "manual", ""),
    ("액화천연가스 LNG", "list-9", "0", "", "약어", "pool", ""),
    ("GI 강판", "list-10", "0", "", "약어", "pool", ""),
    ("나사 M8", "", "1", "", "약어", "manual", ""),
    ("고무 패킹", "", "1", "", "영문", "manual", ""),
]


def write_gold(path, rows=GOLD, source="test"):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for text, exp, nm, hp, style, ls, split in rows:
            w.writerow({c: "" for c in COLUMNS} | {"bom_text": text, "expected_dataset_id": exp, "is_no_match": nm, "hard_pair_group": hp,
                                                   "input_style": style, "label_source": ls, "split": split, "source": source})
    return path


@pytest.fixture
def evaldb(tempdb):  # noqa: F811
    """0001~0003 적용, 합성 데이터셋 10행, 가짜 임베더로 활성 인덱스."""
    migrate(tempdb)
    seed(tempdb, DATASETS)
    build_index(tempdb, FakeEmbedder(), activate=True, log=quiet)
    return tempdb


KNOWN = {f"list-{sn}" for sn, *_ in DATASETS}


def test_validate_collects_every_error_with_row_numbers(tmp_path):
    rows = [
        ("A", "list-1", "0", "", "약어", "pool", ""),
        ("A", "list-2", "0", "", "약어", "pool", ""),        # 3행: bom_text 중복
        ("B", "list-1", "1", "", "약어", "pool", ""),        # 4행: 정답 없음인데 id 있음
        ("C", "", "0", "", "약어", "pool", ""),              # 5행: id 없음
        ("D", "list-999", "0", "", "약어", "pool", ""),      # 6행: 없는 id
        ("E", "list-1", "0", "", "", "pool", "train"),       # 7행: input_style 빈칸, split 값
        ("F", "list-1", "2", "", "약어", "auto", ""),        # 8행: is_no_match 값, label_source 값
    ]
    _, header, parsed = read_csv(write_gold(tmp_path / "g.csv", rows))
    errs = validate(header, parsed, KNOWN)
    got = {(n, msg.split(" ")[0]) for n, msg in errs}
    assert (3, "bom_text") in got and (4, "is_no_match=1") in got and (5, "expected_dataset_id") in got
    assert (6, "lci_dataset") in got and (7, "input_style") in got and (7, "split") in got
    assert (8, "is_no_match") in got and (8, "label_source") in got
    assert len(errs) >= 8  # 한꺼번에 모아 보고


def test_validate_missing_columns(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("bom_text,expected_dataset_id\nA,list-1\n", encoding="utf-8")
    _, header, parsed = read_csv(p)
    [(n, msg)] = validate(header, parsed, KNOWN)
    assert n is None and "필수 열" in msg and "input_style" in msg


def test_assign_splits_is_deterministic_and_balanced(tmp_path):
    _, _, parsed = read_csv(write_gold(tmp_path / "g.csv"))
    a, b = assign_splits(parsed), assign_splits(parsed)
    assert a == b
    for style in ("약어", "영문", "띄어쓰기"):
        ns = [n for n, r in parsed if r["input_style"] == style]
        dev = sum(a[n] == "dev" for n in ns)
        assert dev - (len(ns) - dev) in (0, 1)  # 번갈아 배정: dev 가 같거나 하나 많다
    fixed = [(*r[:6], "test") for r in GOLD]
    _, _, parsed2 = read_csv(write_gold(tmp_path / "g2.csv", fixed))
    assert set(assign_splits(parsed2).values()) == {"test"}  # 적힌 split 은 그대로


@needs_db
def test_load_is_idempotent_by_sha256(evaldb, tmp_path):
    p = write_gold(tmp_path / "g.csv")
    gold_id, created = load(evaldb, p, "t", "v1")
    again, created2 = load(evaldb, p, "other-name", "v9")  # 같은 파일 → 새로 만들지 않음
    assert (gold_id, created, again, created2) == ("gold-t-v1", True, "gold-t-v1", False)
    with psycopg.connect(evaldb) as conn:
        assert conn.execute("SELECT count(*) FROM gold_set").fetchone()[0] == 1
        assert conn.execute("SELECT count(*), count(*) FILTER (WHERE split = 'dev') FROM gold_label").fetchone() == (12, 7)
    with pytest.raises(SystemExit, match="이미 있고"):  # 같은 이름·버전에 다른 내용
        load(evaldb, write_gold(tmp_path / "g3.csv", GOLD[:5]), "t", "v1")


@needs_db
def test_load_rejects_invalid_file(evaldb, tmp_path):
    with pytest.raises(SystemExit, match="오류 1건"):
        load(evaldb, write_gold(tmp_path / "g.csv", [("A", "list-999", "0", "", "약어", "pool", "")]), "bad", "v1")
    with psycopg.connect(evaldb) as conn:
        assert conn.execute("SELECT count(*) FROM gold_set").fetchone()[0] == 0


@needs_db
def test_migration_0003_constraints(evaldb):
    with psycopg.connect(evaldb, autocommit=True) as conn:
        conn.execute("INSERT INTO gold_set (gold_id, name, version, sha256) VALUES ('g', 'n', 'v', 'h')")
        ins = ("INSERT INTO gold_label (gold_id, bom_text, expected_dataset_id, is_no_match, input_style, split) "
               "VALUES ('g', %s, %s, %s, 's', %s)")
        with pytest.raises(errors.CheckViolation):
            conn.execute(ins, ("a", "list-1", 1, "dev"))  # 정답 없음인데 id
        with pytest.raises(errors.CheckViolation):
            conn.execute(ins, ("b", None, 0, "dev"))  # 정답 있음인데 id 없음
        with pytest.raises(errors.CheckViolation):
            conn.execute(ins, ("c", "list-1", 0, "train"))  # split 값
        with pytest.raises(errors.ForeignKeyViolation):
            conn.execute(ins, ("d", "list-999", 0, "dev"))  # lci_dataset 에 없는 id
        with pytest.raises(errors.UniqueViolation):
            conn.execute("INSERT INTO gold_set (gold_id, name, version, sha256) VALUES ('g2', 'n2', 'v', 'h')")  # 같은 sha256
        conn.execute(ins, ("e", "list-1", 0, "dev"))
        with pytest.raises(errors.UniqueViolation):
            conn.execute(ins, ("e", "list-2", 0, "dev"))  # 같은 정답셋 안 bom_text 중복
