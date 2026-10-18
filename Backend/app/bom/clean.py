"""BOM 행 정제. 원문(raw)은 그대로 두고 clean 을 만든다. 사전·속성 추출은 아직 없어 이 정제만으로 검색 질의(norm_text)를 만든다."""
import hashlib
import math
import re
import unicodedata

# 입력(공백 제거·소문자) → (정규 단위, 화면 표기). 화면 표기가 None 이면 원문 그대로 보인다
UNITS = {}
for keys, unit, display in [
    (("kg", "킬로그램", "㎏"), "kg", "kg"),
    (("g", "그램"), "g", "g"),
    (("t", "ton", "톤", "미터톤"), "t", "톤"),
    (("ea", "개", "pcs", "pc", "個", "ea."), "EA", "개"),
    # 점용접의 점은 개수(T13.1): 국가 DB 2024 SPOT 용접의 기준 흐름이 "Number of items"(Item(s))다. 표기는 원문을 둔다
    (("spot", "점", "타점"), "EA", None),
    (("m", "미터"), "m", "m"),
    (("mm", "밀리미터"), "mm", "mm"),
    (("m2", "㎡", "제곱미터"), "m2", "m²"),
    (("m3", "m³", "㎥", "세제곱미터"), "m3", "m³"),
    (("l", "ℓ", "리터"), "L", "L"),
]:
    for k in keys:
        UNITS[k] = (unit, display)


def clean_text(s):
    """NFKC(전각→반각 등), 앞뒤·연속 공백 정리."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def norm_unit(raw):
    """(unit 또는 None, unit_display). 표에 없으면 (None, 원문)."""
    key = re.sub(r"\s+", "", raw or "").lower()
    hit = UNITS.get(key) or UNITS.get(unicodedata.normalize("NFKC", key).lower())
    if not hit:
        return None, (raw or "").strip()
    return hit[0], hit[1] or (raw or "").strip()


def parse_qty(raw):
    """(수량 또는 None, 문제 문구 또는 None)."""
    s = (raw or "").strip().replace(",", "")
    try:
        q = float(s)
    except ValueError:
        return None, "수량 읽을 수 없음"
    if not math.isfinite(q):
        return None, "수량 읽을 수 없음"
    return q, "수량 이상(0 이하)" if q <= 0 else None


# 구분 열 값(공백 제거·소문자) → 역할 코드. 표에 없는 값은 null 로 두고 issues 에 적는다
ROLE_INPUT = {**dict.fromkeys(("소재", "재료", "원자재", "자재", "material"), "material"), **dict.fromkeys(("공정", "가공", "process"), "process")}


def norm_role(raw):
    """(역할 코드 또는 None, 문제 문구 또는 None)."""
    key = re.sub(r"\s+", "", raw or "").lower()
    if not key:
        return None, None
    role = ROLE_INPUT.get(key)
    return role, None if role else f"구분 값을 알 수 없음: {clean_text(raw)}"


def query_key(norm_text, role):
    """같은 품명이라도 구분이 다르면 다른 검색이다. 구분이 없으면 T13 이전과 같은 키(기존 결과·캐시가 맞는다)."""
    return hashlib.sha256((f"{role}{norm_text}" if role else norm_text).encode("utf-8")).hexdigest()


def clean_rows(rows):
    """rows: [{source_row, name, spec, unit, quantity, role?, part_no?}] (원문 문자열). 반환: bom_item 용 dict 목록(row_no 1부터)."""
    out, seen = [], {}
    for i, r in enumerate(rows, start=1):
        name, spec = clean_text(r["name"]), clean_text(r["spec"])
        unit, display = norm_unit(r["unit"])
        qty, qty_issue = parse_qty(r["quantity"])
        norm_text = re.sub(r"\s+", " ", f"{name} {spec}" if spec else name).strip().lower()
        input_role, role_issue = norm_role(r.get("role"))
        issues = []
        if role_issue:
            issues.append(role_issue)
        if qty_issue:
            issues.append(qty_issue)
        if unit is None:
            issues.append("단위 확인 필요")
        dup_key = (norm_text, unit, input_role)
        if norm_text and dup_key in seen:
            issues.append(f"중복 행(원본 {seen[dup_key]}행과 같음)")
        elif norm_text:
            seen[dup_key] = r["source_row"]
        if not name:
            target = ("제외", "품명 없음")
        elif qty is None or unit is None:
            target = ("검토", " · ".join(x for x in (qty is None and "수량 읽을 수 없음", unit is None and "단위 확인 필요") if x))
        else:
            target = ("대상", "")
        out.append({
            "row_no": i, "source_row": r["source_row"],
            "raw_name": r["name"], "raw_spec": r["spec"], "raw_unit": r["unit"], "raw_qty": r["quantity"],
            "clean_name": name, "clean_spec": spec, "clean_unit": unit, "clean_unit_display": display, "clean_qty": qty,
            "norm_text": norm_text, "query_key": query_key(norm_text, input_role), "input_role": input_role,
            "part_no": clean_text(r.get("part_no")) or None,
            "issues": issues, "target_status": target[0], "target_reason": target[1],
        })
    return out


def extract(header, rows, mapping):
    """매핑대로 4필드 원문을 뽑는다. 규격처럼 매핑이 없는 필드는 빈 문자열."""
    idx = {m["field"]: (header.index(m["source"]) if m["source"] else None) for m in mapping}
    def cell(r, field):  # 매핑에 없는 필드(규격·구분·부품번호)는 빈 문자열
        return r[idx[field]] if idx.get(field) is not None else ""
    return [{"source_row": n, "name": cell(r, "품명"), "spec": cell(r, "규격"), "unit": cell(r, "단위"), "quantity": cell(r, "수량"),
             "role": cell(r, "구분"), "part_no": cell(r, "부품번호")} for n, r in rows]
