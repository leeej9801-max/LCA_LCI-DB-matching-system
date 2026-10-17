// 행 상태: review.status → match_state → 검토 필요 (07-API명세서 Row 절). 화면이 공유하는 상태 계산은 이것 하나다
export const rowStatus = (row) => {
  const { status } = row.review
  if (status === 'approved' || status === 'rejected' || status === 'excluded') return status
  if (row.match_state === 'vetoed' || row.match_state === 'no_answer') return row.match_state
  return 'review'
}
