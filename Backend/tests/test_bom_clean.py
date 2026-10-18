"""컬럼 매핑·정제 시험(DB 없음)."""
import hashlib

import pytest

from app.bom.clean import clean_rows, extract, norm_unit, parse_qty
from app.bom.mapping import detect, missing_required, parse_mapping
from app.errors import ApiError


def by_field(m):
    return {x["field"]: (x["source"], x["method"], x["sample"]) for x in m}


def test_aliases_auto_and_missing():
    header = ["No", "Part Name", "사양(mm)", "UOM", "소요량 (EA)", "자재명"]
    m = detect(header, ["1", "강판", "", "kg", "2", "중복"], {})
    assert by_field(m) == {"품명": ("Part Name", "auto", "강판"), "규격": ("사양(mm)", "auto", None),  # 빈 칸 → sample null
                           "단위": ("UOM", "auto", "kg"), "수량": ("소요량 (EA)", "auto", "2"),  # 별칭이 둘 맞으면 첫 컬럼
                           "구분": (None, "missing", None), "부품번호": (None, "missing", None)}  # 선택 열: 없어도 오류가 아니다
    m = detect(["품명", "규격"], ["A", "B"], {})
    assert missing_required(m) == ["단위", "수량"] and by_field(m)["수량"] == (None, "missing", None)


def test_mapping_override_and_errors():
    m = detect(["이름", "개수", "unit"], ["A", "3", "kg"], parse_mapping('{"품명": "이름", "수량": "개수"}'))
    assert by_field(m)["품명"] == ("이름", "manual", "A") and by_field(m)["단위"] == ("unit", "auto", "kg")
    with pytest.raises(ApiError) as e:
        detect(["이름"], ["A"], {"품명": "없는열"})
    assert (e.value.code, e.value.meta) == ("UNKNOWN_COLUMN", {"columns": ["없는열"]})
    for bad in ("{not json", '["품명"]', '{"무게": "kg"}', '{"품명": 3}'):
        with pytest.raises(ApiError) as e:
            parse_mapping(bad)
        assert e.value.code == "INVALID_MAPPING" and e.value.status == 400
    assert parse_mapping("") == {} and parse_mapping(None) == {}


@pytest.mark.parametrize("raw,unit,display", [
    ("kg", "kg", "kg"), (" KG ", "kg", "kg"), ("킬로그램", "kg", "kg"), ("㎏", "kg", "kg"),
    ("g", "g", "g"), ("그램", "g", "g"),
    ("t", "t", "톤"), ("Ton", "t", "톤"), ("톤", "t", "톤"), ("미터톤", "t", "톤"),
    ("ea", "EA", "개"), ("EA.", "EA", "개"), ("개", "EA", "개"), ("pcs", "EA", "개"), ("PC", "EA", "개"), ("個", "EA", "개"),
    ("m", "m", "m"), ("미터", "m", "m"), ("mm", "mm", "mm"), ("밀리미터", "mm", "mm"),
    ("m2", "m2", "m²"), ("㎡", "m2", "m²"), ("제곱미터", "m2", "m²"),
    ("l", "L", "L"), ("ℓ", "L", "L"), ("리터", "L", "L"),
    ("회", None, "회"), ("", None, ""),
    ("spot", "EA", "spot"), ("Spot", "EA", "Spot"), (" SPOT ", "EA", "SPOT"), ("점", "EA", "점"), ("타점", "EA", "타점"),  # 표기는 원문 그대로
])
def test_unit_table(raw, unit, display):
    assert norm_unit(raw) == (unit, display)


@pytest.mark.parametrize("raw,qty,issue", [
    ("1,200", 1200.0, None), (" 2.5 ", 2.5, None), ("0", 0.0, "수량 이상(0 이하)"), ("-3", -3.0, "수량 이상(0 이하)"),
    ("abc", None, "수량 읽을 수 없음"), ("", None, "수량 읽을 수 없음"), ("nan", None, "수량 읽을 수 없음"),
])
def test_quantity(raw, qty, issue):
    assert parse_qty(raw) == (qty, issue)


def test_clean_rows_duplicates_target_and_source_row():
    rows = [
        {"source_row": 2, "name": "ＳＰＣＣ  냉연강판", "spec": " 1.2T ", "unit": "kg", "quantity": "1,200"},
        {"source_row": 4, "name": "SPCC 냉연강판", "spec": "1.2T", "unit": "KG", "quantity": "3"},   # 2행과 같은 자재
        {"source_row": 5, "name": "", "spec": "", "unit": "kg", "quantity": "1"},                   # 품명 없음
        {"source_row": 6, "name": "볼트", "spec": "", "unit": "", "quantity": "x"},                  # 단위·수량 문제
        {"source_row": 7, "name": "SPCC 냉연강판", "spec": "1.2T", "unit": "EA", "quantity": "1"},  # 단위가 달라 중복 아님
    ]
    out = clean_rows(rows)
    a, b, c, d, e = out
    assert (a["clean_name"], a["clean_spec"], a["clean_qty"], a["norm_text"]) == ("SPCC 냉연강판", "1.2T", 1200.0, "spcc 냉연강판 1.2t")
    assert a["raw_name"] == "ＳＰＣＣ  냉연강판"  # 원문 그대로
    assert [x["row_no"] for x in out] == [1, 2, 3, 4, 5] and [x["source_row"] for x in out] == [2, 4, 5, 6, 7]
    assert b["issues"] == ["중복 행(원본 2행과 같음)"] and a["issues"] == [] and e["issues"] == []
    assert a["query_key"] == b["query_key"] == e["query_key"]
    assert (c["target_status"], c["target_reason"]) == ("제외", "품명 없음")
    assert (d["target_status"], d["target_reason"]) == ("검토", "수량 읽을 수 없음 · 단위 확인 필요")
    assert d["issues"] == ["수량 읽을 수 없음", "단위 확인 필요"] and a["target_status"] == "대상"


def test_extract_without_spec_column():
    mapping = [{"field": "품명", "source": "이름"}, {"field": "규격", "source": None}, {"field": "단위", "source": "u"},
               {"field": "수량", "source": "q"}, {"field": "구분", "source": None}, {"field": "부품번호", "source": None}]
    assert extract(["q", "이름", "u"], [(2, ["1", "A", "kg"])], mapping) == [
        {"source_row": 2, "name": "A", "spec": "", "unit": "kg", "quantity": "1", "role": "", "part_no": ""}]


def test_role_and_part_no_aliases_and_values():
    header = ["Part No", "유형", "품명", "단위", "수량"]
    m = by_field(detect(header, ["P1", "공정", "프레스", "kg", "1"], {}))
    assert m["부품번호"] == ("Part No", "auto", "P1") and m["구분"] == ("유형", "auto", "공정")
    for h in ("구분", "역할", "자재구분", "type", "ROLE"):
        assert by_field(detect([h, "품명", "단위", "수량"], ["x", "a", "kg", "1"], {}))["구분"][0] == h
    for h in ("부품번호", "품번", "부품코드", "p/n", "part number"):
        assert by_field(detect([h, "품명", "단위", "수량"], ["x", "a", "kg", "1"], {}))["부품번호"][0] == h
    assert missing_required(detect(["품명", "단위", "수량"], ["a", "kg", "1"], {})) == []  # 선택 열은 필수가 아니다


@pytest.mark.parametrize("raw,role,issue", [
    ("소재", "material", None), (" 재료 ", "material", None), ("원자재", "material", None), ("자재", "material", None), ("Material", "material", None),
    ("공정", "process", None), ("가공", "process", None), ("PROCESS", "process", None),
    ("", None, None), ("  ", None, None), (None, None, None),
    ("부품", None, "구분 값을 알 수 없음: 부품"),
])
def test_role_values(raw, role, issue):
    row = clean_rows([{"source_row": 2, "name": "A", "spec": "", "unit": "kg", "quantity": "1", "role": raw, "part_no": " P-1 "}])[0]
    assert row["input_role"] == role and row["part_no"] == "P-1"
    assert [i for i in row["issues"] if i.startswith("구분")] == ([issue] if issue else [])


def test_query_key_unchanged_without_role_and_differs_with_role():
    base = {"source_row": 2, "name": "프레스 가공", "spec": "", "unit": "kg", "quantity": "1"}
    old = hashlib.sha256("프레스 가공".encode("utf-8")).hexdigest()
    none, mat, proc = (clean_rows([base | ({"role": r} if r is not None else {})])[0] for r in (None, "소재", "공정"))
    assert none["query_key"] == old and none["input_role"] is None and none["part_no"] is None  # 열이 없는 BOM 은 T13 전과 같다
    assert mat["query_key"] == hashlib.sha256("material\x1f프레스 가공".encode("utf-8")).hexdigest()
    assert len({old, mat["query_key"], proc["query_key"]}) == 3
    dup = clean_rows([base | {"role": "소재"}, base | {"role": "공정"}])
    assert all(not any("중복" in i for i in r["issues"]) for r in dup)  # 구분이 다르면 같은 품명도 중복이 아니다
