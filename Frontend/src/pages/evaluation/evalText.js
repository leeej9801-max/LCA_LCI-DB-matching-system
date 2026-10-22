// 성능 확인 화면의 고정 문구 (design/ux-copy-eval-dashboard.md 와 Figma 시안). 숫자는 여기에 두지 않고 리포트에서 읽는다.
// 합격 판정(decisions 2026-10-19): "높음" 비율 ≥ 45% 그리고 "높음" 오류율 점추정 ≤ 10%. 5%는 지향일 뿐 목표선이 아니다
export const HIGH_ERROR_GOAL = 0.1
export const HIGH_COVERAGE_GOAL = 0.45
export const TOTAL_DATASETS = 849 // 국가 LCI DB 공개 목록 (decisions "전체 건수 표기")

export const SPEC_NOTE = '가상 BOM 2000은 규격이 검색어에 모두 들어갔습니다. 공개 문서 표기 등 앞선 시험은 일부 행의 규격이 검색어에 빠진 채 측정되었습니다.'
// 입력 유형별 막대(가상 BOM 2000 리포트의 slices.input_style 키 → 화면 이름, 이 순서로 그린다)
export const STYLE_NAMES = { std: '표준 이름', typo: '오타·띄어쓰기', en: '영문', abbr: '약어·강종 코드', broad: '넓은 이름(상위 개념)' }
export const STYLE_NOTE = '약어·강종 코드와 넓은 이름이 어렵습니다. 사전을 넓히고 모호한 입력을 안내하는 것이 다음 과제입니다.'
export const BULK_NOTE = '같은 재료가 여러 행에 나오므로 실제 독립 표본 수는 2000보다 적고, 입력 문장과 정답을 AI가 직접 만든 합성 데이터입니다.'

// 탭 2·3 화면 머리 부제와 카드 제목·부제 (U11). 제목은 평가 용어(16자 이내), 부제는 쉬운 말 한 줄
export const EVAL_HEAD_SUB = '정답 데이터 기반 매칭 성능 평가'
export const MINE_HEAD_SUB = '업로드 BOM 처리·검토 현황'
export const NOTICE_TITLE = '평가 데이터 안내'
export const NOTICE_BODY = { bulk: 'AI가 만든 합성 데이터 · 정답 라벨 사람 검수 전 · 참고용', p1: '실제 문서의 표기 · 정답 라벨 AI 부여, 사람 검수 전' }
export const TITLES = {
  work: ['검토 작업 분포', '100건 기준 · 데이터별 비교'],
  level: ['신뢰도 등급별 정답률', '등급이 높을수록 정답률이 높은지'],
  recall: ['Top-K 재현율', '상위 K개 후보 안에 정답이 포함된 비율'],
  errors: ['오답 유형', '대표 사례와 개선 방향'],
  none: ['미매칭 판정', 'DB에 없는 품목을 "맞는 후보 없음"으로 분류했는지'],
  style: ['입력 유형별 Top-1 정답률', '표기 방식에 따른 차이'],
  methods: ['구성 요소별 성능 비교', 'Top-1 정답률 기준 · 방식 D = 앱 적용 방식'],
  unknown: ['평가 한계', null],
  next: ['향후 과제', null],
}
export const GOAL_OVER_NOTE = '구간이 목표선을 넘습니다'

export const HUMAN_WORK = [
  { key: 'approve', title: '근거 확인 후 승인', sub: '1순위 추천을 확인만 함' },
  { key: 'choose', title: '후보 비교 선택', sub: '상위 3개 중에서 고름' },
  { key: 'find', title: '수동 탐색', sub: '추천 안에 정답 없음' },
]

// 방식 A~D (pick.js METHODS 와 같은 순서). 케이스 코드의 풀이는 terms.eval_cases
export const METHOD_SUBS = [
  ['방식 A', '글자와 의미를 함께 비교'],
  ['방식 B', 'A + 품목 사전 + 소재·공정 구분'],
  ['방식 C', 'B + 같은 이름 묶기'],
  ['방식 D · 앱이 쓰는 방식', '의미 비교 + 사전 + 구분 + 이름 묶기'],
]
export const METHODS_NOTE = '방식 사이의 차이가 작으면 신뢰구간이 겹쳐 우열을 가리기 어렵습니다.'
export const DROPPED = [
  '후보를 다시 정렬하는 모델 — 정확도가 오르지 않고, "없음" 오판이 늘었습니다',
  'AI 판정 — 같은 품목을 다시 물으면 절반 넘게 답이 바뀌었습니다',
]

export const ERROR_TYPES = [
  ['제품 코드·강종 기호', 'SGACUD, P601', '규격 사전 넓히기'],
  ['영문 약어', 'CFRP, TPO', '약어 사전 넓히기'],
  ['넓은 이름', '특수강, 고무', '올릴 때 보완 요청'],
  ['구매 부품', '볼트, LCD 모듈', '"맞는 후보 없음" 판단 강화'],
]
export const NO_ANSWER_NOTE = '아직 대부분 놓칩니다. DB에 없는 품목에도 후보를 내므로 승인 전에 확인이 필요합니다.'

export const UNKNOWN = ['실제 회사 BOM에서의 성능', '사람이 확인한 정답 기준의 성능', '구매 부품이 얼마나 섞여 있는지']
export const NEXT = ['규격·약어 사전 넓히기 (새 데이터로 다시 측정)', '회사별 표기와 승인 이력 기억하기', '애매한 품목은 올리기 전에 보완 요청']
