// "내가 올린 BOM" 탭의 통계 (U9 2절). A02 의 rows 만 읽는 순수 함수 한 곳. 정답이 없으므로 정답률·정확도는 만들지 않는다.
// 값이 없으면 지어내지 않는다: 나눌 수가 0이면 비율은 null(화면은 "-").
export const LEVELS = ['높음', '보통', '낮음']
export const WORK = ['asIs', 'other', 'manual', 'none', 'pending']
export const SMALL_N = 10 // 승인한 행이 이보다 적으면 "승인 N건 기준, 참고용"

// 시스템 1위 = 차단되지 않은 첫 후보
export const topOf = (row) => row.candidates.find((c) => c.veto == null) ?? null

// 사람이 한 일 (행마다 하나). 승인 여부가 먼저, 그다음 반려·제외·맞는 후보 없음, 나머지는 아직 안 봄
export const workOf = (row, top = topOf(row)) => {
  if (row.review.status === 'approved') {
    if (row.selected?.manual) return 'manual'
    return top && row.selected_id === top.dataset_id ? 'asIs' : 'other'
  }
  if (row.review.status === 'rejected' || row.review.status === 'excluded' || row.match_state === 'no_answer') return 'none'
  return 'pending'
}

const ratio = (n, d) => (d === 0 ? null : n / d)

export const sessionStats = (rows) => {
  const target = rows.filter((r) => r.target.status !== '제외')
  const levels = { 높음: 0, 보통: 0, 낮음: 0, none: 0 }
  const work = Object.fromEntries(WORK.map((w) => [w, 0]))
  const byLevel = Object.fromEntries(LEVELS.map((l) => [l, { approved: 0, asIs: 0 }]))
  let approved = 0
  for (const row of target) {
    const top = topOf(row)
    const w = workOf(row, top)
    work[w] += 1
    // 신뢰도 분포: 맞는 후보 없음(no_answer)이거나 차단되지 않은 1위가 없으면 따로 센다
    levels[row.match_state === 'no_answer' || !top ? 'none' : top.confidence] += 1
    if (row.review.status === 'approved') {
      approved += 1
      if (top) {
        byLevel[top.confidence].approved += 1
        if (w === 'asIs') byLevel[top.confidence].asIs += 1
      }
    }
  }
  return {
    uploaded: rows.length, target: target.length, levels, work, approved,
    highRate: ratio(levels['높음'], target.length),
    asIsRate: ratio(work.asIs, approved),
    byLevel: Object.fromEntries(LEVELS.map((l) => [l, { ...byLevel[l], rate: ratio(byLevel[l].asIs, byLevel[l].approved) }])),
  }
}
