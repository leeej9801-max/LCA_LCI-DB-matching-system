// 후보 비교 패널의 "같은 등급 정답률". 숫자는 최종 평가 결과를 이 파일 상수로 옮긴 것이다(API에서 읽지 않는다).
// 출처: eval-20261020-151720-gold-bulk-v1-test(가상 BOM 2000 검증용), eval-20261020-004831-gold-p1-v1-test(공개 문서 표기 58개).
// 앱 조합 C1+G+D+Vd, 신뢰도 규칙 R1 τ=0.55. 칸에는 검증용 값만, 공개 문서 표기 값은 alt 로 ⓘ에 둔다 (사용자 결정 2026-10-20).
// rate: 0~100 사이 숫자(%) 또는 null, n: 그 등급의 행 수 또는 null, basis: 값의 기준. basis 는 칸 아래에 항상 보여 준다.
const BASIS = '가상 BOM 2000 (검증용) 기준 · AI 라벨'

export const CONFIDENCE_RATES = [
  { level: '높음', rate: 90.1, n: 739, basis: BASIS },
  { level: '보통', rate: 47.5, n: 1032, basis: BASIS },
  { level: '낮음', rate: 17.9, n: 229, basis: BASIS },
]

// 칸 옆 ⓘ 에 쓰는 다른 데이터의 값. rates: 등급 → [정답률 %, 행 수]
export const ALT_RATES = {
  label: '공개 문서 표기 58개',
  rates: { 높음: [68.4, 19], 보통: [27.6, 29], 낮음: [20.0, 10] },
}

// 등급 이름 → 항목. 없는 등급이면 null
export const rateOf = (level) => CONFIDENCE_RATES.find((r) => r.level === level) ?? null

// 칸에 쓰는 글자: 값이 있으면 "N%", 없으면 "측정 중"
export const rateText = (level) => {
  const r = rateOf(level)
  return r?.rate == null ? '측정 중' : `${r.rate}%`
}

// 칸 아래 작은 글씨. 값이 있는 항목의 basis 를 쓰고, 모두 비어 있어도 basis 는 보여 준다
export const rateBasis = () => CONFIDENCE_RATES.find((r) => r.basis)?.basis ?? ''

// basis 옆 ⓘ 문구. "공개 문서 표기 58개" → "공개 문서 표기 데이터에서는 높음 68.4%(19행), …"
export const rateAltText = () => {
  const parts = Object.entries(ALT_RATES.rates).map(([level, [rate, n]]) => `${level} ${rate.toFixed(1)}%(${n}행)`)
  return `${ALT_RATES.label.replace(/ \d+개$/, '')} 데이터에서는 ${parts.join(', ')}였습니다. 입력 표기에 따라 크게 달라집니다.`
}
