"""환산 규칙 시험(순수 함수). 규칙 번호는 T9b §2."""
import pytest

from app.bom.convert import convert, fmt, sig6


def c(qty, unit, ds_unit, amount=None, display=None, **ov):
    return convert(qty, unit, display or unit, ds_unit, amount, ov)


def test_rule2_quantity_missing():
    assert c(None, "kg", "kg") == {"status": "invalid", "value": None, "unit": "kg", "message": "수량이 없습니다", "missing": [], "method": None}


def test_rule3_dataset_without_unit():
    r = c(1.0, "kg", None)
    assert (r["status"], r["value"], r["message"]) == ("incompatible", None, "이 데이터셋은 기준흐름 단위가 없습니다. 다른 데이터셋을 고르세요")
    assert r["unit"] is None and c(None, "kg", "")["unit"] is None  # 빈 문자열이 아니라 null
    assert c(1, "kg", None, amount=3.6)["message"] == "이 데이터셋은 기준흐름 단위가 없습니다. 다른 데이터셋을 고르세요"


def test_dataset_item_s_and_spot_are_ea():
    r = c(4, "EA", "Item(s)", display="ea")
    assert (r["status"], r["value"], r["unit"], r["method"]) == ("ok", 4.0, "EA", "identity")
    r = c(4, "EA", "Spot", display="spot")  # 점용접의 점 = 개수 1 (T13.1, 이전 결정 변경)
    assert (r["status"], r["value"], r["unit"]) == ("ok", 4.0, "EA")


def test_rule4_bom_unit_missing():
    r = c(1.0, None, "kg", display="회")
    assert (r["status"], r["missing"]) == ("needs_info", ["단위"])


def test_rule5_same_unit_including_dataset_aliases():
    assert c(2.4, "kg", "kg")["status"] == "ok"
    r = c(3, "t", "ton")  # 데이터셋 표기 ton → 정규 t
    assert (r["status"], r["value"], r["unit"], r["method"]) == ("ok", 3.0, "t", "identity")
    assert c(2, "m3", "㎥")["status"] == "ok" and c(5, "EA", "EA")["status"] == "ok"


@pytest.mark.parametrize("qty,unit,ds,value,message", [
    (1200, "g", "kg", 1.2, "1,200 g = 1.2 kg"),
    (2.5, "kg", "ton", 0.0025, "2.5 kg = 0.0025 t"),
    (1500, "mm", "m", 1.5, "1,500 mm = 1.5 m"),
    (2000, "L", "m3", 2.0, "2,000 L = 2 m3"),
    (1, "kg", "g", 1000.0, "1 kg = 1,000 g"),
])
def test_rule6_same_group_factor(qty, unit, ds, value, message):
    r = c(qty, unit, ds)
    assert (r["status"], r["value"], r["message"], r["method"]) == ("converted", value, message, "factor")


def test_rule7_count_to_mass_needs_unit_mass_then_converts():
    r = c(20, "EA", "kg", display="개")
    assert (r["status"], r["missing"], r["message"]) == ("needs_info", ["개당 중량"], "개당 중량이 필요합니다")
    r = c(20, "EA", "kg", display="개", unit_mass_kg=0.35)
    assert (r["status"], r["value"], r["method"]) == ("converted", 7.0, "unit_mass")
    assert c(4, "EA", "t", display="개", unit_mass_kg=500)["value"] == 2.0  # 2,000 kg → 2 t


def test_rule8_area_and_volume_to_mass():
    r = c(0.8, "m2", "kg", display="m²", density_kg_m3=7850)
    assert (r["status"], r["missing"], r["message"]) == ("needs_info", ["두께"], "두께 입력이 필요합니다")
    assert c(0.8, "m2", "kg", display="m²")["missing"] == ["두께", "밀도"]
    r = c(0.8, "m2", "kg", display="m²", thickness_mm=2, density_kg_m3=2700)
    assert (r["status"], r["value"], r["method"]) == ("converted", 4.32, "area×thickness×density")  # 0.8 × 0.002 × 2700
    r = c(500, "L", "kg", density_kg_m3=900)
    assert (r["status"], r["value"], r["method"]) == ("converted", 450.0, "volume×density")  # 0.5 m3 × 900


def test_rule9_mass_to_area_and_volume():
    r = c(4.32, "kg", "m2", thickness_mm=2, density_kg_m3=2700)
    assert (r["status"], r["value"], r["method"]) == ("converted", 0.8, "mass÷(thickness×density)")
    r = c(900, "kg", "m3", density_kg_m3=900)
    assert (r["status"], r["value"], r["method"]) == ("converted", 1.0, "mass÷density")
    assert c(900, "kg", "L", density_kg_m3=900)["value"] == 1000.0
    assert c(1, "kg", "m3")["missing"] == ["밀도"] and c(1, "kg", "m2")["missing"] == ["두께", "밀도"]


@pytest.mark.parametrize("qty,unit,ds,display", [
    (3, "m", "kg", "m"), (1, "kg", "MJ", "kg"), (1, "kg", "tonkm", "kg"), (1, "EA", "m2", "개"), (1, "kg", "Item(s)", "kg"),
])
def test_rule10_incompatible(qty, unit, ds, display):
    r = c(qty, unit, ds, display=display)
    assert r["status"] == "incompatible" and r["value"] is None and r["message"].startswith(f"단위 '{display}'는 기준흐름 단위(")


def test_rounding_is_six_significant_digits():
    assert sig6(1 / 3) == 0.333333 and sig6(123456789) == 123457000.0 and sig6(0.000123456789) == 0.000123457
    assert c(1, "g", "t")["value"] == 1e-06 and c(1, "kg", "g", )["value"] == 1000.0
    assert c(10, "EA", "kg", display="개", unit_mass_kg=1 / 3)["value"] == 3.33333
    assert (fmt(1234567.0), fmt(1e-06), fmt(1200.0), fmt(0.0024)) == ("1,234,570", "0.000001", "1,200", "0.0024")


def test_dataset_amount_not_one_goes_to_message_only():
    r = c(2.4, "kg", "톤", amount=3500)
    assert r["value"] == 0.0024 and r["message"] == "2.4 kg = 0.0024 t (데이터셋 기준량 3,500 t)"
    assert c(1, "kg", "kg", amount=1)["message"] == "기준흐름 단위와 같음"
    assert c(1, "kg", "kg", amount=1000)["message"].endswith("(데이터셋 기준량 1,000 kg)")
