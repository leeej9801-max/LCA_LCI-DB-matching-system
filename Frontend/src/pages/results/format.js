// 상태 키(status.js) → [글자, 색 계열]
export const STATUS = {
  approved: ['승인됨', 'ok'],
  rejected: ['반려', 'none'],
  excluded: ['제외', 'none'],
  vetoed: ['차단', 'block'],
  no_answer: ['정답 없음', 'none'],
  review: ['검토 필요', 'warn'],
}

// states가 null이면 전체
export const TABS = [
  { key: 'review', label: '검토 필요', states: ['review'] },
  { key: 'blocked', label: '차단·정답 없음', states: ['vetoed', 'no_answer'] },
  { key: 'approved', label: '승인됨', states: ['approved'] },
  { key: 'closed', label: '반려·제외', states: ['rejected', 'excluded'] },
  { key: 'all', label: '전체', states: null },
]

// 추출 속성 [키, 값] → [이름, 값 글자]. 키 끝 _mm은 단위로 옮긴다
export const attrParts = ([k, v]) => [
  k.replace(/_mm$/, ''),
  v === true ? '예' : v === false ? '아니오' : k.endsWith('_mm') ? `${v}mm` : String(v),
]
export const attrLine = (attrs) => Object.entries(attrs).map((e) => attrParts(e).join(' ')).join(' · ')

export const confidenceText = (c) => `${c.confidence} ${c.score.toFixed(2)}`

// 환산 표시는 응답값 그대로 글자만 붙인다. 계산은 하지 않는다
export const conversionLabel = (row) => {
  const c = row.conversion
  if (!c) return '—'
  if (c.status === 'ok') return `${c.unit} 그대로`
  if (c.status === 'converted') return `${c.value} ${c.unit}로 환산`
  if (c.status === 'needs_info') return `${c.missing.join(', ')} 필요`
  if (c.status === 'incompatible') return `단위 불가(${row.clean.unit_display ?? row.raw.unit})`
  return c.message
}

// 같은 동명 그룹 안의 1·2위는 점수가 같아도 근소로 보지 않는다 (ambiguous 가 true 여도 화면에서 한 번 더 거른다)
export const isClose = (row) => {
  const [first, second] = row.candidates
  return row.ambiguous && !first?.duplicate_group?.others.includes(second?.dataset_id)
}

// 일괄 승인 대상: 현재 선택(기본 선택은 1순위)의 신뢰도 높음 + 환산 ok/converted. 아니면 이유를 돌려준다
export const bulkBlock = (row) => {
  const s = row.selected
  if (!s || s.manual) return '선택된 후보가 없거나 차단·직접 선택입니다'
  if (s.confidence !== '높음') return '선택한 후보의 신뢰도가 높음이 아닙니다'
  if (!['ok', 'converted'].includes(row.conversion?.status)) return '환산이 완료되지 않았습니다'
  return null
}

export const conversionDone = (row) => ['ok', 'converted'].includes(row.conversion?.status)
