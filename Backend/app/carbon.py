"""배출계수(carbon) 객체: lci_dataset 의 gwp_* 열 → API 의 Carbon. 값이 없으면 None(0이나 다른 데이터셋 값으로 채우지 않는다)."""
UNIT = "kg CO₂e"


def carbon_of(total, fossil, biogenic, luluc, method, per):
    """기후변화 합계가 없으면 None. 값은 기준 단위 1당(적재 때 정규화됨), per 는 그 기준 단위."""
    if total is None:
        return None
    num = lambda v: None if v is None else float(v)  # noqa: E731
    return {"total": float(total), "fossil": num(fossil), "biogenic": num(biogenic), "land_use": num(luluc),
            "unit": UNIT, "per": per, "method": method or "Climate change"}
