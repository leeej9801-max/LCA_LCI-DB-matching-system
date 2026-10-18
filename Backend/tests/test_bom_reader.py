"""BOM 파일 읽기 시험(DB 없음)."""
import io

import openpyxl
import pytest

from app.bom.reader import MAX_BYTES, MAX_ROWS, read_bom
from app.errors import ApiError


def err(fn):
    with pytest.raises(ApiError) as e:
        fn()
    return e.value


def test_csv_utf8_bom_and_cp949_and_delimiters():
    text = "품명,단위,수량\n냉연강판,kg,2.4\n"
    for data in (text.encode("utf-8"), ("\ufeff" + text).encode("utf-8"), text.encode("cp949")):
        assert read_bom("a.csv", data) == (["품명", "단위", "수량"], [(2, ["냉연강판", "kg", "2.4"])])
    for d in (";", "\t"):
        assert read_bom("a.csv", text.replace(",", d).encode("utf-8"))[1] == [(2, ["냉연강판", "kg", "2.4"])]


def test_delimiter_ignores_quoted_commas_and_source_row_counts_blank_lines():
    data = 'name;spec;"a,b,c,d"\n\nX;"1,2";3\n'.encode("utf-8")  # 따옴표 안 쉼표 4개는 세지 않는다 → 세미콜론
    header, rows = read_bom("a.csv", data)
    assert header == ["name", "spec", "a,b,c,d"] and rows == [(3, ["X", "1,2", "3"])]  # 빈 2행을 건너뛰어도 원본 줄 번호 3


def test_duplicate_header_and_short_rows():
    header, rows = read_bom("a.csv", " 품명 ,품명,단위,품명\nA,B\n".encode("utf-8"))
    assert header == ["품명", "품명.2", "단위", "품명.3"] and rows == [(2, ["A", "B", "", ""])]


def xlsx(sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_bom_sheet_or_first_sheet():
    data = xlsx([("표지", [["제목"]]), ("BOM", [[None], ["품명", "수량"], ["강판", 2.0], ["볼트", 1.5]])])
    assert read_bom("a.xlsx", data) == (["품명", "수량"], [(3, ["강판", "2"]), (4, ["볼트", "1.5"])])  # 1행 빈 줄, 숫자 2.0 → "2"
    data = xlsx([("Sheet1", [["품명"], ["A"]]), ("기타", [["x"], ["y"]])])
    assert read_bom("a.XLSX", data) == (["품명"], [(2, ["A"])])


def test_errors():
    assert err(lambda: read_bom("a.csv", b"x" * (MAX_BYTES + 1))).code == "FILE_TOO_LARGE"
    assert err(lambda: read_bom("a.xls", b"abc")).code == "UNREADABLE_FILE"
    assert err(lambda: read_bom("a.csv", b"")).code == "UNREADABLE_FILE"
    assert err(lambda: read_bom("a.csv", "품명\n\n".encode())).code == "UNREADABLE_FILE"  # 헤더만
    assert err(lambda: read_bom("a.xlsx", b"not a zip")).code == "UNREADABLE_FILE"
    big = ("품명\n" + "a\n" * (MAX_ROWS + 1)).encode()
    e = err(lambda: read_bom("a.csv", big))
    assert (e.status, e.code, e.meta) == (400, "TOO_MANY_ROWS", {"rows": MAX_ROWS + 1, "limit": MAX_ROWS})
    assert len(read_bom("a.csv", ("품명\n" + "a\n" * MAX_ROWS).encode())[1]) == MAX_ROWS  # 2,000행은 통과
