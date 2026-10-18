import csv
import zipfile
from datetime import datetime
from pathlib import Path

import shutil

import pytest

from tools.link_files import OUT_COLS, excel_year, hard_conflict, korean_tail, link, normalize, normalize_filename, write_csv

LIST_HEADER = "lci_database_sn,category,name_ko,name_en,org,year,version,zip_file,excel_file,registered\n"
KEITI = "환경부(한국환경산업기술원)"


def test_normalize_drops_space_paren_hyphen():
    assert normalize(" 폴리프로필렌 (PP)-사출_공정 ") == "폴리프로필렌pp사출공정"
    assert normalize("A-B (c)") == "abc"


def test_excel_year_serial_text_and_plain():
    assert excel_year(36799) == 2000  # 엑셀 일련번호 = 2000-09-30
    assert excel_year("36799") == 2000
    assert excel_year("2003년 7월") == 2003
    assert excel_year(2005.0) == 2005
    assert excel_year(datetime(2012, 3, 4)) == 2012
    assert excel_year("") is None
    assert excel_year("미상") is None


def test_hard_rules():
    assert hard_conflict("Aluminium billet A1050", "Aluminium billet A6063")  # 합금 기호가 다르다
    assert not hard_conflict("Aluminium billet A1050", "Aluminium billet, A1050")
    assert hard_conflict("Steel sheet", "Recycled steel sheet")  # 재활용 여부
    assert hard_conflict("스테인리스 강판", "Steel sheet")  # 스테인리스 여부
    assert hard_conflict("Aluminium, primary, ingot", "Aluminium ingot")  # 1차 여부
    assert not hard_conflict("Cold rolled steel", "Cold rolled steel sheet")


def test_korean_tail():
    assert korean_tail("LCI-2024-312_폴리프로필렌(PP) 사출 공정.zip") == "폴리프로필렌(PP) 사출 공정"
    assert korean_tail("(LCI-2024-350) NCM 복합액.zip") == "NCM 복합액"
    assert korean_tail("LCI-2022-048 (1).zip") == ""
    assert korean_tail("LCI-2024-310.zip") == ""


def make_zip(path, base_name):
    xml = (
        "<processDataSet><processInformation><dataSetInformation><name>"
        f'<baseName xml:lang="en">{base_name}</baseName></name></dataSetInformation>'
        "<quantitativeReference><referenceToReferenceFlow>1</referenceToReferenceFlow></quantitativeReference>"
        '</processInformation><exchanges><exchange dataSetInternalID="1"><referenceToFlowDataSet refObjectId="f1">'
        "<common:shortDescription>Flow</common:shortDescription></referenceToFlowDataSet><meanAmount>1.0</meanAmount>"
        "</exchange></exchanges></processDataSet>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ILCD/processes/p.xml", xml)


def setup(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    # 파일명이 목록과 같은 파일, 목록에 없는 파일 2개
    make_zip(raw / "LCI-2024-001.zip", "Steel sheet cold rolled")
    make_zip(raw / "LCI-2024-002.zip", "Aluminium extrusion product")
    make_zip(raw / "LCI-2024-003.zip", "Polypropylene injection")
    rows = [
        (1, "냉연강판", "Steel sheet cold rolled", "LCI-2024-001.zip"),
        (2, "알루미늄 압출품", "Aluminium extrusion product", ""),
        (3, "폴리프로필렌 사출", "Polypropylene injection", ""),
        (4, "다른 것", "Something else entirely", ""),
    ]
    list_csv = tmp_path / "list.csv"
    list_csv.write_text(LIST_HEADER + "".join(f"{sn},금속,{ko},{en},{KEITI},2024,1.0.0,{z},,2026-01-01\n" for sn, ko, en, z in rows), encoding="utf-8-sig")
    return list_csv, raw, tmp_path / "download-map.csv"


def read_out(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_exact_and_fuzzy_link(tmp_path):
    list_csv, raw, out = setup(tmp_path)
    write_csv(out, link(list_csv, raw, out)["out_rows"])
    by_file = {r["file"]: r for r in read_out(out)}
    assert by_file["LCI-2024-001.zip"]["status"] == "exact" and by_file["LCI-2024-001.zip"]["list_row"] == "1"
    assert by_file["LCI-2024-001.zip"]["method"] == "name" and by_file["LCI-2024-001.zip"]["name_check"] == "1.000"
    # 보조 경로는 점수가 0.99 이상이어도 review (auto 금지)
    fuzzy = by_file["LCI-2024-002.zip"]
    assert fuzzy["list_row"] == "2" and float(fuzzy["score"]) >= 0.99
    assert fuzzy["status"] == "review" and fuzzy["method"] == "fuzzy"
    assert by_file["LCI-2024-003.zip"]["list_row"] == "3"


def test_confirmed_rows_survive_rerun(tmp_path):
    list_csv, raw, out = setup(tmp_path)
    write_csv(out, link(list_csv, raw, out)["out_rows"])
    rows = read_out(out)
    for r in rows:  # 사람이 002 파일을 4번 행으로 고쳤다고 하자
        if r["file"] == "LCI-2024-002.zip":
            r["list_row"], r["confirmed"] = "4", "Y"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        w.writerows(rows)

    write_csv(out, link(list_csv, raw, out)["out_rows"])
    by_file = {r["file"]: r for r in read_out(out)}
    assert by_file["LCI-2024-002.zip"]["list_row"] == "4" and by_file["LCI-2024-002.zip"]["confirmed"] == "Y"
    assert by_file["LCI-2024-002.zip"]["name_ko"] == "다른 것"  # 표시 열은 목록에서 다시 채운다
    assert by_file["LCI-2024-003.zip"]["list_row"] == "3"
    assert by_file["LCI-2024-001.zip"]["status"] == "exact"


def test_normalize_filename():
    assert normalize_filename("골판지_ GtG_CtG sheet.xls") == normalize_filename("골판지 GtG_CtG sheet.xls")
    assert normalize_filename("A (1).zip") == normalize_filename("A.zip")
    assert normalize_filename("Data.XLS") == normalize_filename("Data.xls")
    assert normalize_filename("골판지\x80 GtG_CtG sheet.xls") == normalize_filename("골판지_ GtG_CtG sheet.xls")  # 목록의 깨진 글자
    assert normalize_filename("A.zip") != normalize_filename("B.zip")


def test_name_norm_links_renamed_file(tmp_path):
    list_csv, raw, out = setup(tmp_path)
    (raw / "LCI-2024-001.zip").rename(raw / "LCI-2024-001 (1).zip")
    by_file = {r["file"]: r for r in read_out_after(link(list_csv, raw, out), out)}
    row = by_file["LCI-2024-001 (1).zip"]
    assert (row["list_row"], row["status"], row["method"]) == ("1", "exact", "name_norm")


def test_same_content_on_two_rows_keeps_best_name(tmp_path):
    list_csv, raw, out = setup(tmp_path)
    shutil.copy(raw / "LCI-2024-001.zip", raw / "LCI-2024-009.zip")  # 사이트가 다른 행에 같은 파일을 내려준 경우
    text = list_csv.read_text(encoding="utf-8-sig")
    list_csv.write_text(text + f"9,금속,폴리프로필렌 수지,Polypropylene resin,{KEITI},2024,1.0.0,LCI-2024-009.zip,,2026-01-01\n", encoding="utf-8-sig")
    rows = {r["list_row"]: r for r in read_out_after(link(list_csv, raw, out), out)}
    assert rows["1"]["status"] == "exact"
    assert rows["9"]["status"] == "content_mismatch" and rows["9"]["top3"] == "belongs_to:1"
    assert rows["9"]["file"] == "LCI-2024-009.zip"


def test_confirmed_survives_old_csv_without_new_columns(tmp_path):
    list_csv, raw, out = setup(tmp_path)
    old_cols = [c for c in OUT_COLS if c not in ("method", "name_check")]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:  # T10a 때 만든 CSV(새 열 없음)를 사람이 고쳤다
        w = csv.DictWriter(f, fieldnames=old_cols)
        w.writeheader()
        w.writerow({c: "" for c in old_cols} | {"file": "LCI-2024-003.zip", "list_row": "4", "status": "review", "confirmed": "Y"})
    rows = {r["file"]: r for r in read_out_after(link(list_csv, raw, out), out)}
    assert rows["LCI-2024-003.zip"]["list_row"] == "4" and rows["LCI-2024-003.zip"]["confirmed"] == "Y"


def read_out_after(result, out):
    write_csv(out, result["out_rows"])
    return read_out(out)


# ---------- T13.1: 기준 단위 보정 ----------
# 표는 파일 이름의 UUID 로 키를 잡으므로 UUID 모양으로 둔다
FP_MASS, FP_ITEMS = "11111111-0000-0000-0000-000000000001", "11111111-0000-0000-0000-000000000002"
UG_MASS, UG_ITEMS = "22222222-0000-0000-0000-000000000001", "22222222-0000-0000-0000-000000000002"


def ilcd_zip(path, exchanges, qref=None, flows=(), props=(), groups=()):
    """exchanges: [(id, 방향, 양, 흐름 id, 이름)]. flows: [(흐름 id, 종류, 흐름 속성 id)]. props: [(id, 이름, 단위 그룹 id)]. groups: [(id, 이름, 단위)]."""
    ex = "".join(
        f'<exchange dataSetInternalID="{i}"><referenceToFlowDataSet refObjectId="{f}"><common:shortDescription>{n}</common:shortDescription>'
        f"</referenceToFlowDataSet><exchangeDirection>{d}</exchangeDirection><meanAmount>{a}</meanAmount></exchange>"
        for i, d, a, f, n in exchanges)
    q = f"<quantitativeReference><referenceToReferenceFlow>{qref}</referenceToReferenceFlow></quantitativeReference>" if qref is not None else ""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ILCD/processes/p.xml", f"<processDataSet><processInformation>{q}</processInformation><exchanges>{ex}</exchanges></processDataSet>")
        for fid, typ, fp in flows:
            z.writestr(f"ILCD/flows/{fid}.xml", f"<flowDataSet><typeOfDataSet>{typ}</typeOfDataSet>"
                                               f'<referenceToFlowPropertyDataSet refObjectId="{fp}"/></flowDataSet>')
        for pid, name, ug in props:
            z.writestr(f"ILCD/flowproperties/{pid}.xml", f'<x><common:name xml:lang="en">{name}</common:name>'
                                                         f'<referenceToReferenceUnitGroup refObjectId="{ug}"/></x>')
        for gid, name, unit in groups:
            z.writestr(f"ILCD/unitgroups/{gid}.xml", f'<x><common:name xml:lang="en">{name}</common:name><referenceToReferenceUnit>0'
                                                     f'</referenceToReferenceUnit><unit dataSetInternalID="0"><name>{unit}</name></unit></x>')


MASS = dict(props=[(FP_MASS, "Mass", UG_MASS)], groups=[(UG_MASS, "Units of mass", "kg")])


def test_unit_from_package_then_table_then_missing(tmp_path):
    from tools.flow_properties import scan
    from tools.link_files import read_zip
    ilcd_zip(tmp_path / "a.zip", [(1, "Output", "1.0", "f1", "Product A")], qref=1, flows=[("f1", "Product flow", FP_MASS)], **MASS)
    assert read_zip(tmp_path / "a.zip")["ref_flow"] | {} == {"name": "Product A", "amount": "1.0", "unit": "kg", "unit_source": "package",
                                                             "missing_flow_property": None, "estimated": False}
    # 흐름 속성 파일이 꾸러미에 없다 → 다른 꾸러미(c.zip)의 정의로 만든 표에서 찾는다
    ilcd_zip(tmp_path / "b.zip", [(1, "Output", "1.0", "f2", "Spot")], qref=1, flows=[("f2", "Product flow", FP_ITEMS)])
    ilcd_zip(tmp_path / "c.zip", [], props=[(FP_ITEMS, "Number of items", UG_ITEMS)], groups=[(UG_ITEMS, "Units of items", "Item(s)")])
    table = {r["flow_property_uuid"]: r for r in scan(tmp_path)}
    assert table[FP_ITEMS] == {"flow_property_uuid": FP_ITEMS, "flow_property_name": "Number of items", "unit_group_name": "Units of items",
                               "reference_unit": "Item(s)", "source_file": "c.zip"}
    import tools.link_files as lf
    zf = zipfile.ZipFile(tmp_path / "b.zip")
    assert lf._flow_unit(zf, "f2", table) == ("Item(s)", "table", None)
    assert lf._flow_unit(zf, "f2", {}) == (None, None, FP_ITEMS)  # 표에도 없으면 비워 두고 UUID 를 남긴다
    zf.close()


def test_scan_stops_when_definitions_differ(tmp_path):
    from tools.flow_properties import scan
    ilcd_zip(tmp_path / "a.zip", [], **MASS)
    ilcd_zip(tmp_path / "b.zip", [], props=[(FP_MASS, "Mass", UG_ITEMS)])
    with pytest.raises(SystemExit, match="정의가 꾸러미마다 다릅니다"):
        scan(tmp_path)


@pytest.mark.parametrize("outputs,expected", [
    ([("Product flow", "1.0")], "P0"),  # 하나뿐 → 채움
    ([("Other flow", "1.0"), ("Waste flow", "1")], None),  # 둘 → 비움
    ([("Product flow", "2.0")], None),  # 없음 → 비움
    ([("Elementary flow", "1.0")], None),  # 요소 흐름은 세지 않는다
    ([("Elementary flow", "1.0"), ("Waste flow", "1.0")], "P1"),
])
def test_reference_flow_fallback_only_when_unique(tmp_path, outputs, expected):
    from tools.link_files import read_zip
    ex = [(i, "Output", a, f"f{i}", f"P{i}") for i, (_, a) in enumerate(outputs)] + [(9, "Input", "1.0", "f9", "In")]
    flows = [(f"f{i}", t, FP_MASS) for i, (t, _) in enumerate(outputs)] + [("f9", "Product flow", FP_MASS)]
    ilcd_zip(tmp_path / "x.zip", ex, flows=flows, **MASS)
    ref = read_zip(tmp_path / "x.zip")["ref_flow"]
    if expected is None:
        assert ref is None
    else:
        assert (ref["name"], ref["unit"], ref["estimated"]) == (expected, "kg", True)


def test_excel_without_section_3_header_reads_unit(tmp_path):
    import openpyxl
    from tools.link_files import read_excel
    wb = openpyxl.Workbook()
    for row in (["1. 프로세스 설명"], ["2. 프로세스 분류"], ["  (2) 프로세스 명칭", "PE 사출"], ["  (3) 명명규칙"], [")"],
                ["  (1) 유형", "생산"], ["  (2) 명칭", "PE 제품"], ["  (3) 단위", "kg"], ["  (4) 양", 1.0], ["4. 프로세스의 기술적 범위", "gate to gate"]):
        wb.active.append(row)
    wb.save(tmp_path / "177.xlsx")
    ref = read_excel(tmp_path / "177.xlsx")["ref_flow"]
    assert (ref["name"], ref["unit"], float(ref["amount"])) == ("PE 제품", "kg", 1.0)


RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


@pytest.mark.skipif(not RAW.exists(), reason="data/raw 없음(국가 DB 원본은 저장소 밖)")
def test_every_package_reference_flow_property_resolves():
    """data/raw 의 모든 ZIP: 기준 흐름의 흐름 속성이 ① 꾸러미 안 또는 ② 표로 풀린다. 풀리지 않는 것은 목록으로 보여 준다.
    지시문의 기대는 0건이었으나 tkm 흐름 속성(00c322dd…)은 단위 그룹 정의가 어느 꾸러미에도 없다(요청서 "막힌 결정"). 그래서
    "정의가 어딘가에 있는데 놓친 것"이 0건인지를 확인한다: 풀리지 않은 UUID 는 모두 표에서도 기준 단위가 비어 있어야 한다."""
    from tools.flow_properties import scan
    from tools.link_files import read_zip
    unresolved, no_ref, sources = [], [], {}
    for p in sorted(RAW.glob("*.zip")):
        try:
            ref = read_zip(p)["ref_flow"]
        except ValueError:
            continue  # processes XML 이 없는 꾸러미(link_files 가 오류로 따로 보고한다)
        if ref is None:
            no_ref.append(p.name)
            continue
        sources[ref["unit_source"]] = sources.get(ref["unit_source"], 0) + 1
        if ref["unit"] is None:
            unresolved.append((p.name, ref["missing_flow_property"]))
    print(f"\n출처 {sources}, 기준 흐름 없음 {len(no_ref)}: {no_ref}, 풀리지 않음 {len(unresolved)}: {unresolved}")
    defined = {r["flow_property_uuid"]: r for r in scan(RAW)}
    missed = [(f, u) for f, u in unresolved if u is None or defined.get(u, {}).get("reference_unit")]
    assert missed == []
    assert {u for _, u in unresolved} <= {"00c322dd-3c48-4af1-a8c5-cb5f56b8018f"}  # 지금 알려진 것은 tkm 하나
