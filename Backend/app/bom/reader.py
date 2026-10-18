"""BOM 파일 읽기(.csv, .xlsx). 반환: (헤더, [(source_row, 값 목록)]). source_row 는 원본 파일의 줄/행 번호(헤더 포함 1부터)."""
import csv
import io
from datetime import date, datetime
from pathlib import PurePath

from app.errors import ApiError

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
DELIMITERS = (",", ";", "\t")


def unreadable(why=""):
    return ApiError(400, "파일을 읽을 수 없습니다. CSV 또는 XLSX 파일인지 확인해 주세요." + (f" ({why})" if why else ""), "UNREADABLE_FILE")


def count_outside_quotes(line, ch):
    n, quoted = 0, False
    for c in line:
        if c == '"':
            quoted = not quoted
        elif c == ch and not quoted:
            n += 1
    return n


def decode(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp949")
        except UnicodeDecodeError as e:
            raise unreadable("인코딩을 알 수 없음") from e


def read_csv(data):
    text = decode(data)
    first = next((line for line in text.splitlines() if line.strip()), "")
    # 첫 줄에서 가장 많이 나온 구분자(같으면 쉼표 > 세미콜론 > 탭). 따옴표 안은 세지 않는다
    delimiter = max(DELIMITERS, key=lambda d: count_outside_quotes(first, d))
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    out = []
    try:
        for record in reader:
            out.append((reader.line_num, record))  # 여러 줄에 걸친 따옴표 칸이면 그 레코드의 마지막 줄 번호
    except csv.Error as e:
        raise unreadable(str(e)) from e
    return out


def cell_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def read_xlsx(data):
    import openpyxl
    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)  # 수식은 저장된 값으로
    except Exception as e:  # openpyxl 은 깨진 파일에 여러 종류 예외를 낸다
        raise unreadable("XLSX 를 열 수 없음") from e
    try:
        ws = book["BOM"] if "BOM" in book.sheetnames else book.worksheets[0]
        # read_only 모드에서 병합 셀은 왼쪽 위에만 값이 있고 나머지는 None 이다
        return [(i, [cell_text(v) for v in row]) for i, row in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1)]
    finally:
        book.close()


def unique_header(cells):
    """앞뒤 공백 제거. 같은 이름이 또 나오면 뒤에 .2, .3 … 을 붙인다."""
    seen, out = {}, []
    for c in cells:
        name = c.strip()
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}.{seen[name]}")
    return out


def read_bom(filename, data):
    if len(data) > MAX_BYTES:
        raise ApiError(413, "파일은 5MB 이하여야 합니다.", "FILE_TOO_LARGE")
    ext = PurePath(filename or "").suffix.lower()
    if ext == ".csv":
        records = read_csv(data)
    elif ext == ".xlsx":
        records = read_xlsx(data)
    else:
        raise unreadable(f"지원하지 않는 확장자 {ext or '(없음)'}")
    records = [(n, r) for n, r in records if any(c.strip() for c in r)]  # 빈 줄은 버린다
    if not records:
        raise unreadable("빈 파일")
    _, head = records[0]
    while head and not head[-1].strip():  # 헤더 오른쪽 빈 칸은 열로 치지 않는다
        head = head[:-1]
    header = unique_header(head)
    rows = [(n, [(r[i] if i < len(r) else "") for i in range(len(header))]) for n, r in records[1:]]
    if not header or not rows:
        raise unreadable("헤더 또는 데이터 행이 없음")
    if len(rows) > MAX_ROWS:
        raise ApiError(400, f"행이 너무 많습니다({len(rows):,}행). 한 번에 {MAX_ROWS:,}행까지 올릴 수 있습니다.", "TOO_MANY_ROWS",
                       {"rows": len(rows), "limit": MAX_ROWS})
    return header, rows
