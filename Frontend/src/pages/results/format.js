import terms from '@/terms'

// 상태 키(status.js) → [글자, 색 계열, terms.js 키(ⓘ)]
export const STATUS = {
  approved: ['승인됨', 'ok', 'approved'],
  rejected: [terms.rejected.label, 'none', 'rejected'],
  excluded: [terms.excluded.label, 'none', 'excluded'],
  vetoed: [terms.veto.label, 'block', 'veto'],
  no_answer: [terms.no_match.label, 'none', 'no_match'],
  review: ['검토 필요', 'warn', null],
}

// states가 null이면 전체
export const TABS = [
  { key: 'review', label: '검토 필요', states: ['review'] },
  { key: 'blocked', label: `${terms.veto.label}·${terms.no_match.label}`, states: ['vetoed', 'no_answer'] },
  { key: 'approved', label: '승인됨', states: ['approved'] },
  { key: 'closed', label: `${terms.rejected.label}·${terms.excluded.label}`, states: ['rejected', 'excluded'] },
  { key: 'all', label: '전체', states: null },
]

// 추출 속성 [키, 값] → [이름, 값 글자]. 키 끝 _mm은 단위로 옮긴다
export const attrParts = ([k, v]) => [
  k.replace(/_mm$/, ''),
  v === true ? '예' : v === false ? '아니오' : k.endsWith('_mm') ? `${v}mm` : String(v),
]
export const attrLine = (attrs) => Object.entries(attrs).map((e) => attrParts(e).join(' ')).join(' · ')

// 환산 표시는 응답값 그대로 글자만 붙인다. 계산은 하지 않는다. 상태 단어는 terms.conversion.states
const CONV = terms.conversion.states
export const conversionLabel = (row) => {
  const c = row.conversion
  if (!c) return '—'
  if (c.status === 'ok') return `${CONV.ok} (${c.unit})`
  if (c.status === 'converted') return `${CONV.converted} · ${c.value} ${c.unit}`
  if (c.status === 'needs_info') return `${c.missing.join('·')} ${CONV.needs}`
  if (c.status === 'incompatible') return `${CONV.incompatible}(${row.clean.unit_display ?? row.raw.unit})`
  return c.message
}

// needs_info 행의 ⓘ: 무엇을 어디에 넣으면 되는지
const INPUT_HINT = { '개당 중량': '부품 1개의 무게(kg/개)', 두께: '판재 두께(mm)', 밀도: '소재 밀도(kg/m³)' }
export const conversionHint = (row) => {
  const c = row.conversion
  if (c?.status !== 'needs_info') return null
  const what = c.missing.map((m) => INPUT_HINT[m] ?? m).join(', ')
  return `"후보 확인"을 눌러 ${what}를 입력하면 데이터셋 기준 단위로 환산합니다.`
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
  if (row.conversion?.status === 'needs_info') return `${row.conversion.missing.join('·')} 입력 필요`
  if (!['ok', 'converted'].includes(row.conversion?.status)) return '환산이 완료되지 않았습니다'
  return null
}

// 부품번호(part_no)가 있는 세션은 부품번호로 묶는다(T13). 묶음 머리: 부품번호 + 소재 행 품명(없으면 첫 행).
// 합본 데이터셋을 고른 소재 행과 같은 부품번호에 공정 행이 있으면 warn(가공이 두 번 계산될 수 있음). all 은 탭에 가려진 행까지 본다
export const groupByPart = (visible, all) => {
  const groups = new Map()
  for (const r of visible) {
    const key = r.part_no ?? ''
    if (!groups.has(key)) groups.set(key, { key: key || '(없음)', part_no: r.part_no, rows: [] })
    groups.get(key).rows.push(r)
  }
  return [...groups.values()].map((g) => {
    const members = g.part_no ? all.filter((r) => r.part_no === g.part_no) : []
    const material = members.find((r) => r.input_role === '소재') ?? g.rows[0]
    return {
      ...g,
      title: material.clean.name || material.raw.name,
      warn: members.some((r) => r.input_role === '소재' && r.selected?.role === '합본') && members.some((r) => r.input_role === '공정'),
    }
  })
}

export const conversionDone = (row) => ['ok', 'converted'].includes(row.conversion?.status)
