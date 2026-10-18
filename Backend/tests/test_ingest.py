"""적재기 시험. 임시 DB(lci_test_*)에서만 하고 기본 lci DB는 건드리지 않는다."""
import csv
import json
import shutil

import psycopg
import pytest

from app.db.migrate import MIGRATIONS, migrate
from app.ingest import build, load
from test_migrate import needs_db, tempdb  # noqa: F401  (fixture 재사용)

KEITI = "환경부(한국환경산업기술원)"
U1 = "11111111-1111-1111-1111-111111111111"
U8 = "88888888-8888-8888-8888-888888888888"
LIST_COLS = ["lci_database_sn", "category", "name_ko", "name_en", "org", "year", "version", "zip_file", "excel_file", "registered"]
MAP_COLS = ["file", "sha", "kind", "list_row", "name_ko", "name_en", "org", "year", "score", "margin", "status", "method", "name_check",
            "top3", "confirmed"]


def xml(uuid, amount="1.0", unit="kg", sha="a"):
    return {"sha": sha * 64, "kind": "xml", "uuid": uuid, "reference_year": 2022, "geography": "KR", "dataset_type": "LCI result",
            "allocation": "Allocation - mass", "cutoff": "No cut-off", "tech": "tech", "ref_flow": {"name": "flow", "amount": amount, "unit": unit}}


def excel(ref, boundary="Cradle to gate", sha="e"):
    return {"sha": sha * 64, "kind": "excel", "ref_flow": ref, "boundary": boundary}


@pytest.fixture
def inputs(tmp_path):
    """합성 입력 8행: 이슈 코드 8종이 모두 한 번 이상 나온다."""
    lst = [  # sn, 분류, 국문명, 영문명, 기관, 연도, 버전, zip, excel
        (1, "금속", "냉연강판", "Cold rolled steel", KEITI, "2022", "1.0.0", "LCI-2022-001.zip", ""),
        (2, "금속", "열연강판", "Hot rolled steel", KEITI, "2022", "1.0.0", "LCI-2022-002.zip", ""),
        (3, "금속", "황동조", "Brass", "산업통상자원부", "2000", "-", "", "3.xls"),
        (4, "금속", "무연 솔더", "Solder", "산업통상자원부", "2006", "-", "", "4.xls"),
        (5, "금속", "수지입 땜납", "Solder flux wire", "산업통상자원부", "2003", "-", "", "5.xls"),
        (6, "연료", "경유", "Diesel", KEITI, "2022", "1.0.0", "LCI-2022-006.zip", ""),
        (7, "연료", "경유(바이오)", "Diesel bio", KEITI, "", "1.0.0", "", ""),
        (8, "금속", "알루미늄", " Aluminium ", KEITI, "2022", "1.0.0", "LCI-2022-008.zip", ""),
    ]
    features = {
        "LCI-2022-001.zip": xml(U1, amount="1,000"),  # 쉼표 있는 1000
        "LCI-2022-002.zip": xml(U1, sha="b"),  # 같은 uuid
        "3.xls": excel({"name": "황동조 생산", "unit": None, "amount": "1.0"}, boundary="Gate-to-gate"),
        "4.xls": excel({"name": None, "unit": None, "amount": None}, sha="f"),  # 빈 서식
        "LCI-2022-008.zip": xml(U8, amount="abc", sha="c") | {"boundary_hint": "... a gate to gate inventory ..."},
    }
    mp = [
        ("LCI-2022-001.zip", "xml", 1, "exact", "name", "0.900", ""),
        ("LCI-2022-002.zip", "xml", 2, "exact", "name", "0.900", ""),
        ("3.xls", "excel", 3, "exact", "name", "0.800", ""),
        ("4.xls", "excel", 4, "exact", "name", "0.000", ""),
        ("5.xls", "excel", 5, "content_mismatch", "name", "", "belongs_to:3"),
        ("LCI-2022-008.zip", "xml", 8, "exact", "name", "0.700", ""),
    ]
    list_csv, map_csv, feat_json = tmp_path / "list.csv", tmp_path / "map.csv", tmp_path / "features.json"
    with open(list_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(LIST_COLS)
        w.writerows([(*r, "2026-01-01") for r in lst])
    with open(map_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_COLS)
        w.writeheader()
        for file, kind, sn, status, method, check, top3 in mp:
            sha = (features.get(file) or features["3.xls"])["sha"][:12]
            w.writerow({c: "" for c in MAP_COLS} | {"file": file, "sha": sha, "kind": kind, "list_row": sn, "status": status,
                                                    "method": method, "name_check": check, "top3": top3})
    feat_json.write_text(json.dumps(features, ensure_ascii=False), encoding="utf-8")
    return {"list_path": list_csv, "map_path": map_csv, "features_path": feat_json, "report_path": tmp_path / "report.md"}


def counts(ci):
    with psycopg.connect(ci) as conn:
        return (conn.execute("SELECT count(*) FROM lci_dataset").fetchone()[0],
                conn.execute("SELECT count(*) FROM dataset_issue").fetchone()[0])


def test_build_issue_codes_without_db(inputs):
    from app.ingest import read_inputs
    datasets, issues = build(*read_inputs(inputs["list_path"], inputs["map_path"], inputs["features_path"]))
    codes = {c for _, c, *_ in issues}
    assert codes == {"file_missing", "no_ref_flow", "unit_blank", "ref_flow_bad_amount", "ref_flow_amount_not_1", "gate_to_gate",
                     "name_mismatch", "duplicate_uuid"}
    by = {d["list_sn"]: d for d in datasets}
    assert by[8]["name_en"] == "Aluminium"  # 앞뒤 공백만 제거
    assert by[3]["version"] == "-"  # 원문 그대로
    assert by[7]["dev_year"] is None


@needs_db
def test_load(tempdb, inputs):  # noqa: F811
    migrate(tempdb)
    summary = load(tempdb, **inputs)
    assert summary["rows"] == 8
    with psycopg.connect(tempdb) as conn:
        q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        rows = {r[0]: r[1:] for r in q("SELECT list_sn, has_xml, source_file, ilcd_uuid, ref_flow_amount, system_boundary FROM lci_dataset")}
        assert rows[1][:2] == (True, "LCI-2022-001.zip") and str(rows[1][2]) == U1 and rows[1][3] == 1000
        assert rows[2][2] is None  # 같은 uuid 는 작은 sn(1)에만
        assert rows[3][0] is False and rows[3][1] == "3.xls" and rows[3][4] == "Gate-to-gate"
        assert rows[5] == (False, None, None, None, None)  # 사이트 파일 오류: 파일 값 전부 NULL
        assert rows[8][3] is None  # 숫자가 아닌 양
        assert rows[8][4] is None  # XML 의 system_boundary 는 NULL 그대로
        issues = {(r[0], r[1]): r[2] for r in q("SELECT d.list_sn, i.code, i.detail FROM dataset_issue i JOIN lci_dataset d USING (dataset_id)")}
        assert issues[(5, "file_missing")] == {"reason": "site_file_error", "belongs_to": 3}
        assert issues[(6, "file_missing")]["reason"] == "download_needed"
        assert issues[(7, "file_missing")]["reason"] == "no_filename"
        assert issues[(2, "duplicate_uuid")] == {"uuid": U1, "kept_by": 1}
        assert (4, "no_ref_flow") in issues and (4, "name_mismatch") in issues
        assert issues[(8, "gate_to_gate")] == {"source": "xml_text", "excerpt": "... a gate to gate inventory ..."}
        assert issues[(3, "gate_to_gate")] == {"raw": "Gate-to-gate"}
        assert {c for _, c in issues} >= {"unit_blank", "ref_flow_bad_amount", "ref_flow_amount_not_1", "gate_to_gate"}
    assert inputs["report_path"].read_text(encoding="utf-8").startswith("# ingest-report")


@needs_db
def test_load_twice_is_idempotent(tempdb, inputs):  # noqa: F811
    migrate(tempdb)
    load(tempdb, **inputs)
    first = counts(tempdb)
    load(tempdb, **inputs)
    assert counts(tempdb) == first


@needs_db
def test_dry_run_leaves_nothing(tempdb, inputs):  # noqa: F811
    migrate(tempdb)
    summary = load(tempdb, **inputs, dry_run=True)
    assert summary["rows"] == 8  # 계산은 했다
    assert counts(tempdb) == (0, 0)


@needs_db
def test_without_0002_exits(tempdb, inputs, tmp_path):  # noqa: F811
    only_0001 = tmp_path / "m"
    only_0001.mkdir()
    shutil.copy(MIGRATIONS / "0001_data_index_job.sql", only_0001)
    migrate(tempdb, only_0001)
    with pytest.raises(SystemExit, match="0002가 적용되지 않았습니다"):
        load(tempdb, **inputs)


def test_ref_flow_flags_become_issues(inputs):
    """T13.1: 표에서 찾은 단위·추정한 기준 흐름·풀지 못한 흐름 속성은 dataset_issue 로 남는다(사람이 볼 수 있게)."""
    from app.ingest import read_inputs
    rows, mapping, features = read_inputs(inputs["list_path"], inputs["map_path"], inputs["features_path"])
    features["LCI-2022-001.zip"]["ref_flow"] |= {"unit_source": "table", "estimated": True}
    features["LCI-2022-008.zip"]["ref_flow"] |= {"unit": None, "missing_flow_property": "0000-fp"}
    _, issues = build(rows, mapping, features)
    by = {}
    for ds, code, severity, message, detail in issues:
        by.setdefault(ds, {})[code] = (severity, message, detail)
    assert by["list-1"]["ref_flow_estimated"][:2] == ("info", "기준 흐름 추정: flow(XML에 지정 없음)")
    assert by["list-1"]["unit_from_table"][0] == "info"
    assert by["list-8"]["flow_property_missing"] == ("warning", "흐름 속성 정의 없음: 0000-fp", {"uuid": "0000-fp"})
    assert "unit_blank" in by["list-8"]
    assert "ref_flow_estimated" not in by.get("list-2", {}) and "flow_property_missing" not in by.get("list-2", {})
