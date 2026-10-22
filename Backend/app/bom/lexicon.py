"""사전(D): 질의 확장. 순수 함수(E2). 평가 케이스에서만 쓴다(앱 검색 경로에는 아직 넣지 않는다).

- SYNONYMS: 입력에 키가 있으면 질의 뒤에 값을 덧붙인다(원문은 지우지 않는다). 값이 이미 질의에 있으면 덧붙이지 않는다.
- FORM_WORDS: 소재의 형태를 뜻할 뿐 검색을 흐리는 말. TF-IDF 질의에서만 뺀다(밀집 질의는 뺀 것 없이 그대로).
항목 추가·수정은 이 두 표에서만 한다.

출처(ORIGIN, E2b): 이 표는 dev-v2 정답셋이 이미 있는 상태에서 작성했다. 그래서 모든 항목을 "dev-v2 행을 보지 않고 정했다"고 말할 수 없다.
각 항목의 출처를 세 가지로 구분한다.
  std — 규격·표준에 정의된 기호(수지 약어는 ISO 1043-1, 강종 기호는 KS·JIS). 주석에 근거 표준 이름을 적는다.
  db  — 849 목록의 데이터셋 이름에 그 표기가 실제로 있는 업계 통용어. 주석에 근거 데이터셋 id를 적는다.
  dev — dev-v2 행을 본 뒤 추가했거나, 어느 쪽인지 확실하지 않은 것(애매하면 dev). 일반화 성능을 말할 때는 dev 항목의 몫을 빼고 본다(Ds 케이스).
"""
import re

# 키(입력 표기) → 덧붙일 말(국가 DB 이름 표기)
SYNONYMS = {
    # 수지 약어 — 목록 이름은 국문 전체 이름
    "PP": "폴리프로필렌",
    "PE": "폴리에틸렌",
    "HDPE": "고밀도 폴리에틸렌",
    "LDPE": "저밀도 폴리에틸렌",
    "LLDPE": "선형 저밀도 폴리에틸렌",
    "PS": "폴리스티렌",
    "GPPS": "폴리스티렌",
    "HIPS": "내충격성 폴리스티렌",
    "EPS": "발포 폴리스티렌",
    "PC": "폴리카보네이트",
    "PET": "폴리에틸렌 테레프탈레이트",
    "PBT": "폴리부틸렌 테레프탈레이트",
    "PMMA": "폴리메틸메타크릴레이트",
    "POM": "폴리옥시메틸렌",
    "PVC": "폴리비닐클로라이드",
    "ABS": "아크릴로니트릴 부타디엔 스티렌",
    # 강재 규격 기호 — 목록 이름은 제품 형태
    "SPCC": "냉간압연강판",
    "SPHC": "열간압연강판",
    "SGCC": "용융아연도금강판",
    "SECC": "전기아연도금강판",
    "EGI": "전기아연도금강판",
    "STS": "스테인리스",
    "SUS": "스테인리스",
    # 공정 줄임말 — 목록 이름은 '사출성형'·'사출 공정'·'용착'
    "사출": "사출성형",
    "도장": "도장(코팅)",
    "인젝션": "사출",
    "CO2 용접": "GMAW 용접",
    "MIG": "GMAW",
    # 별칭
    "호일": "박",
    "신너": "신나",
    "시너": "신나",
    "캐소드": "전기동",
}
# 소재 형태어(TF-IDF 질의에서만 뺀다)
FORM_WORDS = ("펠릿", "펠렛", "칩", "분말", "파우더", "시트")

ORIGINS = ("std", "db", "dev")
# 키 → 출처. SYNONYMS·FORM_WORDS 의 모든 키가 여기 있어야 한다(시험으로 검사). 주석 = 근거 한 줄
ORIGIN = {
    # --- 수지 약어: ISO 1043-1(플라스틱 기본 중합체 기호) ---
    "PP": "std",  # ISO 1043-1 PP
    "PE": "std",  # ISO 1043-1 PE
    "PS": "std",  # ISO 1043-1 PS
    "PC": "std",  # ISO 1043-1 PC
    "PET": "std",  # ISO 1043-1 PET
    "PBT": "std",  # ISO 1043-1 PBT
    "PMMA": "std",  # ISO 1043-1 PMMA
    "POM": "std",  # ISO 1043-1 POM
    "PVC": "std",  # ISO 1043-1 PVC
    "ABS": "std",  # ISO 1043-1 ABS
    # --- 수지 약어: ISO 기호는 아니고(PE-HD·PS-HI 등이 ISO) 목록 영문명에 그 표기가 있는 통용어 ---
    "HDPE": "db",  # list-66 'High-Density Polyethylene, HDPE', list-801
    "LDPE": "db",  # list-61 'LDPE'
    "GPPS": "db",  # list-81 'General Purpose Polystyrene, GPPS'
    "HIPS": "db",  # list-85 'High Impact Polystyren, HIPS'
    "EPS": "db",  # list-77 'EPS'
    "LLDPE": "dev",  # 목록은 'L-LDPE'(list-782)라 키 표기가 다르다. dev-v2 행(D028)을 본 뒤 추가했고 확실하지 않음
    # --- 강종 기호: KS·JIS ---
    "SPCC": "std",  # JIS G 3141 냉간압연강판
    "SPHC": "std",  # JIS G 3131 열간압연강판
    "SGCC": "std",  # JIS G 3302 용융아연도금강판
    "SECC": "std",  # JIS G 3313 전기아연도금강판
    "STS": "std",  # KS D 3698 등 스테인리스강 기호
    "SUS": "std",  # JIS G 4303 등 스테인리스강 기호
    "EGI": "dev",  # 업계 통용 표기(규격 기호 아님), dev-v2 행(D002)을 본 뒤 추가
    # --- 공정 줄임말·별칭 ---
    "사출": "db",  # list-176·177·178 'PE·PS·PVC 사출성형', list-769 'ABS 사출 공정'
    "도장": "dev",  # dev-v2 행(D-C07·D111)에 걸린다. 값 '도장(코팅)'이 목록 이름에 없다. 지시문 예시를 옮겨 적은 것이라 근거 불확실
    "인젝션": "dev",  # dev-v2 행(D062)을 본 뒤 추가
    "CO2 용접": "dev",  # dev-v2 행(D069)을 본 뒤 추가
    "MIG": "dev",  # dev-v2 행(D070)을 본 뒤 추가
    "호일": "dev",  # dev-v2 행(D011 알루미늄 호일)을 본 뒤 추가(목록은 '알루미늄 박' list-466·102)
    "신너": "dev",  # dev-v2 행(D045 시너)을 본 뒤 추가
    "시너": "dev",  # dev-v2 행(D045)을 본 뒤 추가(목록은 '신나류' list-229)
    "캐소드": "dev",  # dev-v2 초안 행(전기동 캐소드, 최종 dev-v2에서는 빠짐)을 본 뒤 추가(목록은 '전기동' list-108·879)
    # --- 형태어: 지시문 E2 가 예로 든 말을 그대로 옮긴 것으로 규격·목록 근거가 없다. 목록 이름에는 오히려 이 말들이 있어(예: '재활용 HDPE 펠릿' list-658) 뺄 때 해가 될 수 있다 ---
    "펠릿": "dev", "펠렛": "dev", "칩": "dev", "분말": "dev", "파우더": "dev", "시트": "dev",
}


def _pattern(key):
    """영문 키는 앞뒤가 영문자가 아닐 때만(PP 가 PPS 안에서 걸리지 않게), 한글 키는 부분 일치."""
    k = re.escape(key)
    return re.compile(rf"(?<![A-Za-z]){k}(?![A-Za-z])", re.IGNORECASE) if key.isascii() else re.compile(k)


_SYN = [(k, v, _pattern(k)) for k, v in SYNONYMS.items()]
NON_DEV = ("std", "db")  # Ds: dev 출처 항목을 뺀 사전


def hit_origin(hit):
    """expand 가 돌려준 항목('PP→폴리프로필렌', '-펠릿')의 출처."""
    return ORIGIN[hit[1:] if hit.startswith("-") else hit.split("→")[0]]


def expand(text, origins=None):
    """(밀집 질의, TF-IDF 질의, 적용한 항목 목록). 항목은 'PP→폴리프로필렌', '-펠릿' 형식.
    origins 를 주면(예: NON_DEV) 그 출처의 항목만 쓴다. 기본은 전부(D)."""
    text = text or ""
    use = lambda key: origins is None or ORIGIN[key] in origins  # noqa: E731
    hits, extra = [], []
    for key, value, pat in _SYN:
        if use(key) and pat.search(text) and value not in text and value not in extra:
            extra.append(value)
            hits.append(f"{key}→{value}")
    dense = " ".join([text] + extra)
    forms = [w for w in FORM_WORDS if use(w)]
    removed = sorted({w for w in forms if w in text}, key=FORM_WORDS.index)
    form_pat = re.compile("|".join(re.escape(w) for w in forms)) if forms else None
    tfidf = re.sub(r"\s+", " ", form_pat.sub(" ", dense)).strip() if removed else dense
    return dense, tfidf, hits + [f"-{w}" for w in removed]


def origin_counts():
    """사전 항목 수(출처별). SYNONYMS 와 FORM_WORDS 를 합친 개수와 각각의 개수."""
    keys = [*SYNONYMS, *FORM_WORDS]
    return {"total": len(keys), "synonyms": len(SYNONYMS), "form_words": len(FORM_WORDS), **{o: sum(ORIGIN[k] == o for k in keys) for o in ORIGINS}}


def synonyms_sha256():
    """SYNONYMS 표의 해시(match_run.config 에 남겨 어떤 사전으로 돌렸는지 알 수 있게 한다). 키·값·순서가 같으면 같다."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps(SYNONYMS, ensure_ascii=False).encode("utf-8")).hexdigest()
