"""BOM 행 수량을 선택한 데이터셋의 기준흐름 단위로 환산한다(순수 함수, LLM 없음).

규칙은 위에서부터 처음 맞는 것(T9b §2). 값은 유효숫자 6자리. 데이터셋 기준량이 1이 아니어도 값은 바꾸지 않고 message 에만 적는다
(기준량 반영은 계산 A17 의 일).
"""
from decimal import Decimal

from app.bom.clean import norm_unit

# 정규 단위 → (군, 군 기준 단위로의 계수)
FACTORS = {
    "g": ("mass", 0.001), "kg": ("mass", 1.0), "t": ("mass", 1000.0),
    "mm": ("length", 0.001), "m": ("length", 1.0),
    "m2": ("area", 1.0),
    "L": ("volume", 0.001), "m3": ("volume", 1.0),
    "EA": ("count", 1.0),
}
# 데이터셋 쪽에만 있는 표기(ILCD 개수 단위). BOM 단위 표(clean.UNITS)는 바꾸지 않는다
DATASET_UNITS = {"item(s)": "EA", "spot": "EA"}  # Spot(점용접의 점) = 개수 1 (T13.1)


def sig6(x):
    """유효숫자 6자리 반올림(float)."""
    return float(f"{x:.6g}")


def fmt(x):
    """화면용 숫자: 천 단위 쉼표, 유효숫자 6자리, 끝자리 0 없음, 지수 표기 없음(1,200 / 1.2 / 0.000001 / 1,234,570)."""
    return format(Decimal(repr(sig6(x))).normalize(), ",f")


def result(status, unit, message, value=None, missing=(), method=None):
    return {"status": status, "value": value, "unit": unit, "message": message, "missing": list(missing), "method": method}


def convert(quantity, bom_unit, bom_display, ds_unit_raw, ds_amount=None, overrides=None):
    """Conversion. bom_unit 은 clean.unit(정규 단위 또는 None), ds_unit_raw 는 lci_dataset.ref_flow_unit 원문."""
    ov = overrides or {}
    ds_unit = (norm_unit(ds_unit_raw)[0] or DATASET_UNITS.get(ds_unit_raw.strip().lower())) if ds_unit_raw else None
    unit = ds_unit or ds_unit_raw or None  # 데이터셋에 단위가 없으면 null
    note = ""
    if ds_amount is not None and ds_amount not in (0, 1):
        note = f" (데이터셋 기준량 {fmt(ds_amount)}{' ' + unit if unit else ''})"

    if quantity is None:
        return result("invalid", unit, "수량이 없습니다" + note)
    if not ds_unit_raw:
        return result("incompatible", unit, "이 데이터셋은 기준흐름 단위가 없습니다. 다른 데이터셋을 고르세요")
    if bom_unit is None:
        return result("needs_info", unit, "단위를 확인해 주세요" + note, missing=["단위"])
    if ds_unit is None or ds_unit not in FACTORS:
        return incompatible(bom_display, unit, note)
    if bom_unit == ds_unit:
        return result("ok", unit, "기준흐름 단위와 같음" + note, value=sig6(quantity), method="identity")

    b_group, b_f = FACTORS[bom_unit]
    d_group, d_f = FACTORS[ds_unit]
    if b_group == d_group:
        v = quantity * b_f / d_f
        return result("converted", unit, f"{fmt(quantity)} {bom_unit} = {fmt(v)} {unit}{note}", value=sig6(v), method="factor")

    t, d, m = ov.get("thickness_mm"), ov.get("density_kg_m3"), ov.get("unit_mass_kg")
    if b_group == "count" and d_group == "mass":
        if m is None:
            return result("needs_info", unit, "개당 중량이 필요합니다" + note, missing=["개당 중량"])
        v = quantity * m / d_f
        return result("converted", unit, f"{fmt(quantity)} 개 × {fmt(m)} kg/개 = {fmt(v)} {unit}{note}", value=sig6(v), method="unit_mass")
    if b_group in ("area", "volume") and d_group == "mass":
        need = (["두께"] if b_group == "area" and t is None else []) + (["밀도"] if d is None else [])
        if need:
            return result("needs_info", unit, f"{'·'.join(need)} 입력이 필요합니다{note}", missing=need)
        amount = quantity * b_f  # m2 또는 m3
        if b_group == "area":
            v = amount * (t / 1000) * d / d_f
            msg = f"{fmt(quantity)} {bom_display} × {fmt(t)} mm × {fmt(d)} kg/m³ = {fmt(v)} {unit}"
            return result("converted", unit, msg + note, value=sig6(v), method="area×thickness×density")
        v = amount * d / d_f
        return result("converted", unit, f"{fmt(quantity)} {bom_display} × {fmt(d)} kg/m³ = {fmt(v)} {unit}{note}", value=sig6(v),
                      method="volume×density")
    if b_group == "mass" and d_group in ("area", "volume"):
        need = (["두께"] if d_group == "area" and t is None else []) + (["밀도"] if d is None else [])
        if need:
            return result("needs_info", unit, f"{'·'.join(need)} 입력이 필요합니다{note}", missing=need)
        kg = quantity * b_f
        if d_group == "area":
            v = kg / ((t / 1000) * d) / d_f
            msg = f"{fmt(quantity)} {bom_unit} ÷ ({fmt(t)} mm × {fmt(d)} kg/m³) = {fmt(v)} {unit}"
            return result("converted", unit, msg + note, value=sig6(v), method="mass÷(thickness×density)")
        v = kg / d / d_f
        return result("converted", unit, f"{fmt(quantity)} {bom_unit} ÷ {fmt(d)} kg/m³ = {fmt(v)} {unit}{note}", value=sig6(v),
                      method="mass÷density")
    return incompatible(bom_display, unit, note)


def incompatible(bom_display, unit, note):
    return result("incompatible", unit, f"단위 '{bom_display}'는 기준흐름 단위({unit})로 환산할 수 없습니다{note}")
