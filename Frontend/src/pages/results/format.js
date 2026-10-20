import terms, { roleLabel } from '@/terms'
import { shortOrg } from '../datasets/format'

export { shortOrg }

// 상태 키(status.js) → [글자, 칩 색 계열]. 상태 4색(승인 대기 노랑 / 승인 초록 / 맞는 후보 없음 회색 / 반려 빨강)은 상태 칩에만 쓴다 (U7 규칙 2).
// 제외도 회색 계열이다. 차단(vetoed)은 후보가 모두 막힌 것이라 "맞는 후보 없음"으로 묶는다(탭과 같다). 색만으로 구분하지 않도록 글자가 항상 같이 나온다
export const STATUS = {
  review: ['승인 대기', 'wait'],
  approved: ['승인', 'ok'],
  rejected: [terms.rejected.label, 'bad'],
  excluded: [terms.excluded.label, 'none'],
  vetoed: [terms.no_candidate.label, 'none'],
  no_answer: [terms.no_match.label, 'none'],
}

// states가 null이면 전체. 첫 탭이 기본(전체). URL 쿼리 tab 값은 key (옛 링크 호환: review·blocked·approved·closed·all)
export const TABS = [
  { key: 'all', label: '전체', states: null },
  { key: 'review', label: '승인 대기', states: ['review'] },
  { key: 'blocked', label: terms.no_match.label, states: ['vetoed', 'no_answer'] },
  { key: 'approved', label: '승인됨', states: ['approved'] },
  { key: 'closed', label: `${terms.rejected.label}·${terms.excluded.label}`, states: ['rejected', 'excluded'] },
]

// 추출 속성 [키, 값] → [이름, 값 글자]. 키 끝 _mm은 단위로 옮긴다
export const attrParts = ([k, v]) => [
  k.replace(/_mm$/, ''),
  v === true ? '예' : v === false ? '아니오' : k.endsWith('_mm') ? `${v}mm` : String(v),
]

// "기관 · 연도 · 종류" 한 줄 (표의 보조 정보). 없는 값은 "—"
export const orgYearRole = (c) => [shortOrg(c.org), c.year ?? '—', c.role ? roleLabel(c.role) : null].filter((v) => v != null).join(' · ')

// 단위 칸 (U7). 응답값 그대로 글자만 붙이고 계산은 하지 않는다. warn=true 면 amber 경고 문구
const CONV = terms.conversion.states
export const unitCell = (row) => {
  const c = row.conversion
  if (!c) return { text: '—', warn: false }
  if (c.status === 'ok') return { text: c.unit, warn: false }
  if (c.status === 'converted') return { text: `${c.value} ${c.unit}`, warn: false }
  if (c.status === 'needs_info') return { text: c.missing.includes('단위') ? CONV.needsBadge : `${c.missing.join('·')} 필요`, warn: true }
  if (c.status === 'incompatible') return { text: `단위 불일치(${row.clean.unit_display ?? row.raw.unit})`, warn: true }
  return { text: c.message ?? '—', warn: true }
}

// 단위 정보가 필요한 행: 환산이 끝나지 않은 것 (conversion 이 null 이면 세지 않는다)
export const unitOpen = (row) => row.conversion != null && !['ok', 'converted'].includes(row.conversion.status)

// 일괄 승인 대상: 현재 선택(기본 선택은 1순위)의 신뢰도 높음 + 환산 ok/converted. 아니면 이유를 돌려준다
export const bulkBlock = (row) => {
  const s = row.selected
  if (!s || s.manual) return '선택된 후보가 없거나, 차단된 후보·직접 고른 데이터셋입니다. 하나씩 승인하세요'
  if (s.confidence !== '높음') return '신뢰도가 높음이 아닙니다. 후보를 비교한 뒤 하나씩 승인하세요'
  if (row.conversion?.status === 'needs_info') return terms.conversion.input(row.conversion.missing)
  if (!['ok', 'converted'].includes(row.conversion?.status)) return '단위를 변환할 수 없습니다. 다른 후보를 고르세요'
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

// 결과 목록 위 요약 4칸 + 검토 진행 (U7 2-2 ①). 숫자는 rows 에서 센다. 정의:
//  found      후보를 찾은 행   = match_state 가 candidate 인 행 (도구 기준; 차단·맞는 후보 없음은 제외). 분모 total = 전체 행
//  waiting    승인 대기        = 아직 사람이 처리하지 않았고(승인·반려·제외 아님) 후보가 있는 행 (탭 "승인 대기"와 같다). high/mid/low = 현재 선택의 신뢰도별
//  none       맞는 후보 없음   = 처리 전이고 match_state 가 vetoed·no_answer 인 행 (탭 "맞는 후보 없음"과 같다)
//  unit       단위 정보 필요   = 현재 선택 기준으로 환산이 끝나지 않은 행 (승인 상태와 상관없이)
//  approved / closed(반려·제외) / left(남음) = 검토 진행. done = approved + closed
export const summarizeRows = (rows, statusOf) => {
  const status = (r) => statusOf(r)
  const waiting = rows.filter((r) => status(r) === 'review')
  const level = (r) => r.selected?.confidence ?? r.candidates[0]?.confidence
  const approved = rows.filter((r) => status(r) === 'approved').length
  const closed = rows.filter((r) => ['rejected', 'excluded'].includes(status(r))).length
  return {
    total: rows.length,
    found: rows.filter((r) => r.match_state === 'candidate').length,
    waiting: waiting.length,
    high: waiting.filter((r) => level(r) === '높음').length,
    mid: waiting.filter((r) => level(r) === '보통').length,
    low: waiting.filter((r) => level(r) === '낮음').length,
    none: rows.filter((r) => ['vetoed', 'no_answer'].includes(status(r))).length,
    unit: rows.filter(unitOpen).length,
    approved,
    closed,
    done: approved + closed,
    left: rows.length - approved - closed,
  }
}
