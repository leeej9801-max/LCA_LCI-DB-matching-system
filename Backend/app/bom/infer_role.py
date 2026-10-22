"""구분(소재/공정 …) 자동 추정: 품명 끝의 키워드로만 판단하는 순수 함수(T14).

모르면 None 이다(소재 키워드는 만들지 않는다 — None 이면 전체에서 찾는다).
품명이 키워드로 *끝날* 때만 맞는 것으로 본다. '압출재'·'냉간압연강판'·'용접봉'처럼 키워드 뒤에 소재 명사가 붙은 이름이 공정으로 잘못 걸리면
정답 후보가 검색 필터에서 빠지기 때문이다. 검색 필터로 쓰는 것은 process 뿐이다(app/bom/match.py).
"""
import re

# 키워드 뒤에 붙어도 같은 뜻인 말: '분체도장 처리', 'ABS 사출 공정'
SUFFIXES = ("공정", "처리", "작업")
# 역할 → 키워드. 추가·수정은 여기서만 한다. 영문은 소문자로 적는다
KEYWORDS = {
    "waste": ("소각", "매립", "재활용", "폐수"),
    "transport": ("수송", "운송", "운반", "트럭", "선박", "철도"),
    "utility": ("전력", "전기", "스팀", "경유", "휘발유", "lpg", "도시가스", "용수"),
    "process": ("가공", "성형", "사출", "압출", "압연", "용접", "도장", "주조", "절단", "단조", "프레스", "열처리", "도금처리",
                "조립", "세척", "건조"),
}
LABEL_KO = {"process": "공정", "transport": "수송", "waste": "폐기·재활용", "utility": "에너지·유틸리티"}


def _tail_keyword(compact):
    """공백을 뺀 이름이 (키워드 + 접미어*)로 끝나면 그 키워드, 아니면 None. 가장 긴 키워드를 먼저 본다."""
    stripped = compact
    while True:
        for s in SUFFIXES:
            if stripped.endswith(s) and len(stripped) > len(s):
                stripped = stripped[:-len(s)]
                break
        else:
            break
    for candidate in {compact, stripped}:
        for role, words in KEYWORDS.items():
            for w in sorted(words, key=len, reverse=True):
                if candidate.endswith(w):
                    return role, w
    return None


# E2 Veto(평가 케이스 전용): 품명 끝이 이 말이면 소재. 앱의 infer_role 결과는 바꾸지 않는다(앱은 공정만 필터)
MATERIAL_KEYWORDS = ("수지", "펠릿", "펠렛", "레진", "강판", "강재", "코일", "잉곳", "원료", "분말", "섬유", "원단", "필름", "판재", "봉", "선재")


def veto_role(name, spec=""):
    """(material|process|None, reason). 공정은 infer_role 그대로, 소재는 품명 끝 MATERIAL_KEYWORDS.
    소재 키워드로 끝나도 품명 어딘가에 공정 키워드가 있으면 None('냉간압연강판'·'압출 필름'처럼 모르면 모른다)."""
    role, reason = infer_role(name, spec)
    if role == "process":
        return role, reason
    compact = re.sub(r"[\s()（）\[\]]+", "", (name or "").lower())
    word = next((w for w in sorted(MATERIAL_KEYWORDS, key=len, reverse=True) if compact.endswith(w)), None)
    if not word:
        return None, "품명 끝에 소재·공정 키워드가 없음"
    proc = next((w for w in KEYWORDS["process"] if w in compact), None)
    if proc:
        return None, f"품명 끝 '{word}'(소재)와 '{proc}'(공정)가 함께 있어 판단하지 않음"
    return "material", f"품명 끝의 '{word}' → 소재"


def infer_role(name, spec=""):
    """(role|None, reason). role ∈ process, transport, waste, utility, None. spec 은 아직 판단에 쓰지 않는다(품명만 본다)."""
    compact = re.sub(r"[\s()（）\[\]]+", "", (name or "").lower())
    if not compact:
        return None, "품명이 비어 있음"
    hit = _tail_keyword(compact)
    if not hit:
        return None, "품명 끝에 공정·수송·폐기·에너지 키워드가 없음"
    role, word = hit
    return role, f"품명 끝의 '{word}' → {LABEL_KO[role]}"
