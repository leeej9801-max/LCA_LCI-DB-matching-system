"""BOM 컬럼 → 4필드(품명·규격·단위·수량) 매핑. 백엔드가 기준(프론트 mock upload.js 는 같은 규칙에서 출발한 사본)."""
import json
import re

from app.errors import ApiError

# 별칭은 공개 자료(공개 BOM 양식·매뉴얼 예시)에서 본 표기를 바탕으로 한 가정이다. 실제 업체 BOM 으로 확인한 것이 아니다.
FIELDS = [
    ("품명", True, ["품명", "부품명", "자재명", "품목", "품목명", "자재", "partname", "part name", "item", "itemname", "description"]),
    ("규격", False, ["규격", "사양", "재질", "스펙", "spec", "specification", "material"]),
    ("단위", True, ["단위", "수량단위", "unit", "uom"]),
    ("수량", True, ["수량", "소요량", "필요수량", "qty", "quantity"]),
    # 선택 열(T13). 별칭도 공개 자료 기반 가정이다
    ("구분", False, ["구분", "유형", "역할", "자재구분", "type", "role"]),
    ("부품번호", False, ["부품번호", "품번", "부품코드", "partno", "part no", "part number", "p/n"]),
]
FIELD_NAMES = [f for f, _, _ in FIELDS]


def norm(header):
    """비교용: 괄호 안 글자 제거, 공백 제거, 소문자. 예: '수량(EA)' → '수량', 'Part Name' → 'partname'."""
    return re.sub(r"\s+", "", re.sub(r"\([^)]*\)", "", header)).lower()


ALIASES = {field: {norm(a) for a in aliases} for field, _, aliases in FIELDS}


def parse_mapping(raw):
    """A20·A01 의 mapping(JSON 문자열 {"품명": "컬럼명"}). 비었으면 {}."""
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ApiError(400, "mapping 은 JSON 문자열이어야 합니다.", "INVALID_MAPPING") from e
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ApiError(400, 'mapping 은 {"필드": "컬럼명"} 형태여야 합니다.', "INVALID_MAPPING")
    bad = [k for k in value if k not in FIELD_NAMES]
    if bad:
        raise ApiError(400, f"mapping 필드는 {', '.join(FIELD_NAMES)} 중 하나여야 합니다: {', '.join(bad)}", "INVALID_MAPPING",
                       {"fields": bad})
    return value


def detect(header, first_row, override):
    """ColumnMapping 목록(스펙 07). override 의 컬럼이 파일에 없으면 400 UNKNOWN_COLUMN."""
    unknown = [c for c in override.values() if c not in header]
    if unknown:
        raise ApiError(400, f"파일에 없는 컬럼입니다: {', '.join(unknown)}", "UNKNOWN_COLUMN", {"columns": unknown})
    out = []
    for field, required, _ in FIELDS:
        if field in override:
            source, method = override[field], "manual"
        else:
            source = next((h for h in header if norm(h) in ALIASES[field]), None)  # 여럿이면 첫 컬럼
            method = "auto" if source else "missing"
        value = first_row[header.index(source)] if source and first_row else ""
        out.append({"field": field, "required": required, "source": source, "method": method, "sample": value.strip() or None})
    return out


def missing_required(mapping):
    return [m["field"] for m in mapping if m["required"] and m["source"] is None]
