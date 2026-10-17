"""mock JSON 이 계약 모델(app/schemas.py)을 통과하는지 확인한다."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import (
    Dataset, DatasetDetail, DatasetSearchResponse, ErrorBody, RowPatch, SessionPayload,
)

ROOT = Path(__file__).parents[2]
MOCK = ROOT / "Frontend/src/api/mock/data"
FIX = ROOT / "docs/LCA/fixtures"


def load(path):
    """`_`로 시작하는 키(_note 등)는 최상위·중첩 모두 제거한다."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not k.startswith("_")}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    return strip(json.loads(Path(path).read_text(encoding="utf-8")))


def fixture(name):
    """docs/LCA/fixtures 는 git 밖이라 없을 수 있다 → skip."""
    p = FIX / name
    return pytest.param(p, marks=pytest.mark.skipif(not p.exists(), reason=f"{p} 없음"), id=f"fixtures/{name}")


@pytest.mark.parametrize("path", [MOCK / "session.mock.json", fixture("session.mock.json"), fixture("session.sample.json")])
def test_session(path):
    SessionPayload.model_validate(load(path))


@pytest.mark.parametrize("path", [MOCK / "dataset.detail.json", fixture("dataset.detail.json")])
def test_dataset_detail(path):
    DatasetDetail.model_validate(load(path))


@pytest.mark.parametrize("path", [MOCK / "datasets.mock-pool.json", fixture("datasets.mock-pool.json")])
def test_pool_items(path):
    # 풀은 목록+상세 합집합이라 A05 목록 항목(Dataset)의 키만 골라 본다. 상세 전용 키는 A06 시험이 본다
    for item in load(path)["items"]:
        item = {k: item[k] for k in Dataset.model_fields}
        if item["dataset_id"].startswith("mock-"):
            item["list_row"] = 0  # mock-* 예시 항목은 목록 행이 없다 (decisions "mock 예시 표기"). 실제 데이터는 항상 integer
        Dataset.model_validate(item)


@pytest.mark.parametrize("path", [fixture("datasets.search.json")])
def test_datasets_search(path):
    DatasetSearchResponse.model_validate(load(path))


@pytest.mark.parametrize("path", [fixture("errors.sample.json")])
def test_errors(path):
    for case in load(path).values():
        ErrorBody.model_validate(case["body"])


# --- 모델 단위 ---
def session():
    return load(MOCK / "session.mock.json")


def test_missing_nullable_key_fails():
    d = session()
    del d["rows"][0]["selected_id"]
    with pytest.raises(ValidationError):
        SessionPayload.model_validate(d)


def test_unknown_key_fails():
    d = session()
    d["rows"][0]["bogus"] = 1
    with pytest.raises(ValidationError):
        SessionPayload.model_validate(d)


def test_score_out_of_range_fails():
    d = session()
    d["rows"][0]["candidates"][0]["score"] = 1.2
    with pytest.raises(ValidationError):
        SessionPayload.model_validate(d)


def test_unit_mass_zero_fails():
    with pytest.raises(ValidationError):
        RowPatch(unit_mass_kg=0)


def test_attrs_accepts_bool_rejects_null():
    d = session()
    d["rows"][0]["attrs"] = {"재생": True}
    SessionPayload.model_validate(d)
    d["rows"][0]["attrs"] = {"재생": None}
    with pytest.raises(ValidationError):
        SessionPayload.model_validate(d)


def test_attrs_string_true_stays_string():
    d = session()
    d["rows"][0]["attrs"] = {"재생": "true"}
    assert isinstance(SessionPayload.model_validate(d).rows[0].attrs["재생"], str)
