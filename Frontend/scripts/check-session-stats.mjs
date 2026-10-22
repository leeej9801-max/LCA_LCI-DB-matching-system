// sessionStats.js 가 합성 행으로 손으로 센 값과 같은지 확인한다. 실행: node scripts/check-session-stats.mjs
import assert from 'node:assert/strict'
import { sessionStats } from '../src/pages/evaluation/sessionStats.js'

const cand = (id, confidence, veto = null) => ({ dataset_id: id, confidence, veto })
const row = (o) => ({ target: { status: '대상' }, match_state: 'candidate', selected_id: null, selected: null, review: { status: 'pending' }, ...o })
const pick = (id, manual = false) => ({ selected_id: id, selected: { dataset_id: id, manual } })

const rows = [
  row({ candidates: [cand('a', '높음'), cand('b', '보통')], review: { status: 'approved' }, ...pick('a') }), // 1 승인 1위 그대로
  row({ candidates: [cand('a', '보통'), cand('b', '보통')], review: { status: 'approved' }, ...pick('b') }), // 2 승인 다른 추천
  row({ candidates: [cand('a', '낮음')], review: { status: 'approved' }, ...pick('zzz', true) }), // 3 직접 찾아 승인
  row({ candidates: [cand('a', '높음')], review: { status: 'rejected' } }), // 4 반려
  row({ candidates: [cand('a', '보통')], review: { status: 'excluded' } }), // 5 제외
  row({ candidates: [cand('a', '높음')] }), // 6 아직 안 봄
  row({ candidates: [cand('a', '낮음')], match_state: 'no_answer' }), // 7 맞는 후보 없음
  row({ candidates: [cand('v', '높음', { rule_id: 'V1' }), cand('b', '보통')], review: { status: 'approved' }, ...pick('b') }), // 8 차단된 1위 건너뛰고 2위 승인
  row({ candidates: [cand('a', '높음')], target: { status: '제외' } }), // 9 제외 대상: 세지 않음
]
const s = sessionStats(rows)

assert.equal(s.uploaded, 9)
assert.equal(s.target, 8)
assert.deepEqual(s.levels, { 높음: 3, 보통: 3, 낮음: 1, none: 1 }) // 1·4·6 / 2·5·8 / 3 / 7
assert.deepEqual(s.work, { asIs: 2, other: 1, manual: 1, none: 3, pending: 1 }) // 1·8 / 2 / 3 / 4·5·7 / 6
assert.equal(s.approved, 4)
assert.equal(s.highRate, 3 / 8)
assert.equal(s.asIsRate, 2 / 4)
assert.deepEqual(s.byLevel, {
  높음: { approved: 1, asIs: 1, rate: 1 },
  보통: { approved: 2, asIs: 1, rate: 0.5 },
  낮음: { approved: 1, asIs: 0, rate: 0 },
})

// 승인한 행이 0이면 비율은 null(화면은 "-"), 행이 없어도 오류 없이
const none = sessionStats([rows[3], rows[5]])
assert.equal(none.approved, 0)
assert.equal(none.asIsRate, null)
assert.ok(Object.values(none.byLevel).every((l) => l.rate === null))
assert.equal(sessionStats([]).highRate, null)
console.log('ok', JSON.stringify({ levels: s.levels, work: s.work, approved: s.approved }))
