"""Veto(역할 거르기)의 순수 함수. 앱 검색(app.bom.match)과 평가 케이스(app.evaluation.cases)가 같은 함수를 쓴다(E4a).

강등형(Vd)은 반대 역할 후보를 지우지 않고 모두 뒤로 보낸다. 합본(combined)·수송 등 다른 역할은 어느 쪽에서도 움직이지 않는다.
"""
from app.bom.infer_role import veto_role
from app.roles import LABEL

# Veto: 추정 역할 → 거르거나 뒤로 보낼 데이터셋 역할. 합본(combined)·수송 등은 어느 쪽에서도 건드리지 않는다
VETO_EXCLUDE = {"material": "process", "process": "material"}


def effective_role(name, input_role=None):
    """Veto 가 쓰는 구분. 입력 구분(material·process)이 있으면 그것이 우선이고, 없을 때만 이름에서 추정한다(veto_role). 둘 다 없으면 None."""
    if input_role in VETO_EXCLUDE:
        return input_role
    return veto_role(name)[0]


def demote(ranking, role_of, drop_role):
    """강등형 Veto(Vd): drop_role 인 후보를 모두 뒤로 보낸다. 각 묶음 안의 기존 순서는 그대로, 다른 역할(합본 포함)은 움직이지 않는다."""
    keep = [x for x in ranking if role_of.get(x[0]) != drop_role]
    return keep + [x for x in ranking if role_of.get(x[0]) == drop_role]


def veto_filters(role_of):
    """제외형 Veto(V)의 검색 조건: 추정 역할 → (TF-IDF 허용 dataset_id 집합, 밀집 SQL 의 허용 역할 코드 목록)."""
    allowed = {r: {ds for ds, role in role_of.items() if role != ex} for r, ex in VETO_EXCLUDE.items()}
    codes = {r: [c for c in LABEL if c != ex] for r, ex in VETO_EXCLUDE.items()}
    return allowed, codes


def demoted_note(veto_role_code, candidate_role_code):
    """Vd 로 뒤로 밀린 후보의 근거 한 줄. 밀리지 않았으면 None. 예: '역할 다름(소재 입력에 공정 데이터셋) → 뒤로'"""
    if veto_role_code in VETO_EXCLUDE and candidate_role_code == VETO_EXCLUDE[veto_role_code]:
        return f"역할 다름({LABEL[veto_role_code]} 입력에 {LABEL[candidate_role_code]} 데이터셋) → 뒤로"
    return None
