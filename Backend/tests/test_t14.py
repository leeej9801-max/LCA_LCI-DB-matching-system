"""T14: 신뢰도(None 포함)·no_answer 판정·구분 추정·새 필드·서버 문장 용어. DB 없이 도는 순수 함수 시험."""
import csv
import json
from pathlib import Path

import pytest

from app.bom import match
from app.bom.infer_role import infer_role
from app.schemas import Row
from test_bom_match import ITEM, cand, ranked

DATA = Path(__file__).parents[2] / "docs/LCA/data"


@pytest.mark.parametrize("rt,rd,expected", [
    (1, 1, "높음"), (1, 2, "보통"), (3, 3, "보통"), (50, 1, "보통"), (4, 5, "낮음"),
    (None, 1, "낮음"), (1, None, "낮음"), (None, 2, "낮음"), (None, None, "낮음"),
])
def test_confidence_table(rt, rd, expected):
    assert match.confidence(rt, rd) == expected


def row_of(rt, rd, item=ITEM):
    return match.row_payload(item, [ranked("A", rt, rd) | {"confidence": match.confidence(rt, rd)}], {})


def test_no_answer_when_representative_is_low():
    row = row_of(None, 1)
    assert row["match_state"] == "no_answer" and len(row["candidates"]) == 1  # 후보 목록은 지우지 않는다
    assert row["no_answer_reason"] == "글자 유사도 상위 100위 밖이고 의미 유사도 1위뿐이라 근거가 약합니다"
    assert "TF-IDF" not in row["no_answer_reason"] and "밀집" not in row["no_answer_reason"]


@pytest.mark.parametrize("rt,rd", [(1, 1), (1, 3), (2, 2), (3, 1)])
def test_candidate_when_not_low(rt, rd):
    row = row_of(rt, rd)
    assert row["match_state"] == "candidate" and row["no_answer_reason"] is None


def test_no_answer_without_candidates_and_reason_texts():
    row = match.row_payload(ITEM, [], {})
    assert row["match_state"] == "no_answer" and row["no_answer_reason"] == "검색된 후보가 없습니다"
    assert "상위 100위 밖" in match.no_answer_reason(ranked("A", None, None))
    assert "의미 유사도 상위 100위 밖이고 글자 유사도 5위뿐" in match.no_answer_reason(ranked("A", 5, None))
    assert "글자 유사도 6위, 의미 유사도 9위" in match.no_answer_reason(ranked("A", 6, 9))


def test_summary_counts_no_answer():
    rows = [row_of(1, 1), row_of(None, 1), match.row_payload(ITEM, [], {})]
    s = match.summarize([r | {"target": {"status": "대상"}, "review": {"status": "pending"}, "issues": [], "conversion": None} for r in rows])
    assert s["match"] == {"candidate": 1, "vetoed": 0, "no_answer": 2}


def test_new_fields_and_old_fields():
    row = row_of(1, 1)
    assert row["no_answer_reason"] is None and row["inferred_role"] is None
    for k in ("id", "match_state", "candidates", "ambiguous", "selected_id", "selected", "overrides", "review", "conversion", "explanation"):
        assert k in row
    # 계약 모델을 통과한다(필드 없음도 통과: mock 호환)
    base = {k: v for k, v in row.items() if k not in ("no_answer_reason", "inferred_role")}
    assert Row.model_fields["no_answer_reason"].default is None and Row.model_fields["inferred_role"].default is None
    assert set(base) | {"no_answer_reason", "inferred_role"} == set(Row.model_fields)


@pytest.mark.parametrize("name,role", [
    ("프레스 가공", "process"), ("점용접", "process"), ("분체도장 처리", "process"), ("ABS 사출", "process"), ("PP 사출", "process"),
    ("중공성형", "process"), ("ABS 사출 공정", "process"), ("열처리", "process"), ("도금 처리", "process"),
    ("트럭 수송", "transport"), ("해상 운송", "transport"), ("소각", "waste"), ("폐수 처리", "waste"), ("전력", "utility"), ("LPG", "utility"),
    ("SPCC 냉연강판 1.2T", None), ("재생 알루미늄 압출재 A6063", None), ("냉간압연강판", None), ("전기아연도금강판", None),
    ("용접봉", None), ("볼트 M6x20", None), ("ABS 수지 펠릿", None), ("", None),
])
def test_infer_role_table(name, role):
    got, reason = infer_role(name, "")
    assert got == role and reason


def test_inferred_role_is_shown_and_adds_reason():
    item = dict(ITEM) | {"clean_name": "분체도장 처리", "norm_text": "분체도장 처리", "input_role": None}
    row = match.row_payload(item, [ranked("프레스 가공", 1, 1) | {"confidence": "높음"}], {})
    assert row["inferred_role"] == "공정" and row["input_role"] is None
    r = row["candidates"][0]["reasons"]
    # E4a 2-1: 이름에서 추정한 구분은 하드 필터가 아니라 반대 역할 후보를 뒤로 보낸다 → 근거 문구가 바뀐다
    assert "구분 '공정'을 이름에서 자동 추정" in r and "공정 아닌 후보는 뒤로" in r and not any("공정 데이터셋 안에서 찾음" in x for x in r)
    # 입력 구분이 있으면 그것이 우선 — 추정 표시 없음
    given = match.row_payload(item | {"input_role": "material"}, [ranked("A", 1, 1) | {"confidence": "높음"}], {})
    assert given["inferred_role"] is None and not any("자동 추정" in x for x in given["candidates"][0]["reasons"])
    # 소재처럼 보이는 이름은 필터하지 않는다
    mat = match.row_payload(dict(ITEM) | {"clean_name": "압출재"}, [ranked("A", 1, 1) | {"confidence": "높음"}], {})
    assert mat["inferred_role"] is None
    assert match.search_role("material", "프레스 가공", "") == "material" and match.search_role(None, "프레스 가공", "") == "process"
    assert match.search_role(None, "트럭 수송", "") is None  # 수송은 필터에 쓰지 않는다


def test_server_sentences_have_no_internal_terms():
    c = ranked("A", None, 3)
    text = " ".join(match.reasons_for(c, "a", {}, "process", True))
    assert "TF-IDF" not in text and "밀집" not in text and "글자 유사도" in text and "의미 유사도 3위" in text
    assert "TF-IDF" not in match.reasons_for(ranked("A", 2, None), "a", {})[0]


SPLIT = DATA / "sample-bom-split-draft.csv"
SESSION = DATA / "t13-split-draft-session.json"


@pytest.mark.skipif(not SPLIT.exists(), reason="개발 샘플 없음")
def test_infer_role_on_split_sample_has_no_false_positive():
    miss = fp = hit = 0
    for r in csv.DictReader(SPLIT.open(encoding="utf-8-sig")):
        got, _ = infer_role(r["품명"], r["규격"])
        if got == "process" and r["구분"] == "소재":
            fp += 1
        elif got == "process":
            hit += 1
        elif r["구분"] == "공정":
            miss += 1
    assert fp == 0 and hit > 0
