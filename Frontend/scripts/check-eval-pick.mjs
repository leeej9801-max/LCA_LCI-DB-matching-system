// 값 고르기 함수(pick.js)가 리포트에서 U8 1절의 기대값을 내는지 확인한다. 실행: node scripts/check-eval-pick.mjs
// 화면 탭(U9)은 가상 BOM 2000(gold-bulk-v1, 리포트가 있을 때만)과 공개 문서 표기(gold-p1-v1). 110행·튜닝용 리포트는 탭에는 없지만 보존 리포트라 같은 기대값으로 계속 확인한다.
import { readdirSync, readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import { compareGoldId, goalOf, humanWork, pick } from '../src/pages/evaluation/pick.js'
import { CONFIDENCE_RATES } from '../src/data/confidenceRates.js'

const dir = new URL('../../Backend/app/data/eval_reports/', import.meta.url)
const load = (id) => pick(JSON.parse(readFileSync(new URL(`${id}.json`, dir), 'utf8')))
const r1 = (v) => Math.round(v * 1000) / 10
const sets = { // p1 = 화면 탭 3, measure·dev = 보존 리포트
 
  measure: load('eval-20261020-004523-gold-measure-v2-test'),
  p1: load('eval-20261020-004831-gold-p1-v1-test'),
  dev: load('eval-20261020-003528-gold-dev-v2-dev'),
}

// [A Top-1, 높음 행 수, 높음 정답률, 높음 오류율, 오류율 구간, 보통 정답률, 낮음 정답률]; null = 리포트 값(기대값 표에 없음)
const want = {
  measure: [90.8, 70, 92.9, 7.1, [1.4, 14.1], 68.6, 0],
  p1: [48.9, 19, 68.4, 31.6, [10.5, 52.6], 27.6, 20.0],
  dev: [85.1, 61, null, 6.6, null, null, null],
}
for (const [k, [top1, rows, acc, err, ci, mid, low]] of Object.entries(want)) {
  const p = sets[k]
  const got = [r1(p.top1), p.highRows, r1(p.levels['높음'].acc), r1(p.highError), p.highErrorCi.map(r1), r1(p.levels['보통'].acc), r1(p.levels['낮음'].acc)]
  const exp = [top1, rows, acc, err, ci, mid, low]
  exp.forEach((e, i) => { if (e != null) assert.deepEqual(got[i], e, `${k} #${i}`) })
  assert.ok(Math.abs(p.highError - (1 - p.levels['높음'].acc)) < 1e-9, `${k} 높음 오류율 = 1 - 정답률`)
  console.log(k.padEnd(8), 'A Top-1', got[0], '| 높음', got[1], '행', got[2], '% 오류율', got[3], '% 구간', got[4].join('~'), '| 보통', got[5], '% 낮음', got[6], '%')
}
// 화면 탭 2: bulk 리포트가 있으면 값을 고를 수 있는지와 비교 쌍만 확인한다(기대값은 최종 평가 뒤 사람이 정한다). 없으면 건너뛴다
const bulkFile = readdirSync(dir).find((f) => f.includes('gold-bulk-v1') && f.endsWith('.json'))
if (bulkFile) {
  const bulk = load(bulkFile.replace(/\.json$/, ''))
  const h = humanWork(bulk)
  assert.equal(h.approve + h.choose + h.find, 100)
  assert.equal(bulk.goldId, 'gold-bulk-v1')
  console.log('bulk     A Top-1', r1(bulk.top1), 'Top-3', r1(bulk.top3), '행 수', bulk.total, '높음', bulk.highRows, r1(bulk.levels['높음'].acc), '% 비율', r1(bulk.highCoverage), '오류율', r1(bulk.highError), bulk.highErrorCi.map(r1).join('~'), '사람이 할 일', h)
  // U10 기대값
  assert.equal(r1(bulk.top1), 70.4)
  assert.equal(r1(bulk.top3), 81.8)
  assert.equal(bulk.answerable, 1700)
  assert.equal(bulk.highRows, 739)
  assert.equal(r1(bulk.highError), 9.9)
  assert.deepEqual(bulk.highErrorCi.map(r1), [7.6, 12.2])
  assert.equal(r1(bulk.highCoverage), 37.0)
  assert.deepEqual(h, { approve: 37, choose: 45, find: 18 })
  // 입력 유형별 막대: 값이 있는 5개만, 이 순서
  assert.deepEqual(bulk.inputStyles.map((x) => [x.key, r1(x.top1)]), [['std', 83.5], ['typo', 82.5], ['en', 79.5], ['abbr', 56.8], ['broad', 44.0]])
  // 후보 패널 상수(src/data/confidenceRates.js) = bulk 리포트 값(소수 첫째 자리)
  for (const c of CONFIDENCE_RATES) {
    assert.equal(c.rate, r1(bulk.levels[c.level].acc), `상수 ${c.level} 정답률`)
    assert.equal(c.n, bulk.levels[c.level].rows, `상수 ${c.level} 행 수`)
  }
  console.log('상수 = bulk 값:', CONFIDENCE_RATES.map((c) => `${c.level} ${c.rate}%(${c.n})`).join(', '))
  // 목표 배지: 오류율 ≤ 10% 이지만 높음 비율 37.0% < 45% → partial, 구간 상한 12.2% > 10%
  assert.deepEqual(goalOf(bulk), { badge: 'partial', rangeOver: true })
} else {
  console.log('bulk     리포트 없음 — 건너뜀')
}
// 공개 문서 표기 = miss(오류율 31.6% > 10%), 보존 리포트: measure = 비율 63.6%·오류율 7.1% → full, dev = 비율 45.5%·6.6% → full
assert.deepEqual(goalOf(sets.p1), { badge: 'miss', rangeOver: true })
assert.equal(goalOf(sets.measure).badge, 'full')
assert.equal(sets.p1.inputStyles.length, 0) // 공개 문서 표기 리포트는 입력 유형 키가 달라 막대를 그리지 않는다
assert.equal(compareGoldId('gold-p1-v1'), 'gold-bulk-v1')
assert.equal(compareGoldId('gold-bulk-v1'), 'gold-p1-v1')
assert.equal(sets.measure.total, 110)
assert.equal(sets.p1.total, 58)
assert.equal(sets.dev.total, 134)
assert.equal(sets.measure.pairBase, 'C2+D+Vd')
assert.deepEqual(sets.measure.pairs['C1+G+D+Vd'], { new_right: 2, new_wrong: 1, same: 95, rows: 98 })
// 사람이 할 일: 합이 100
for (const [k, p] of Object.entries(sets)) {
  const h = humanWork(p)
  assert.equal(h.approve + h.choose + h.find, 100, k)
  console.log(k.padEnd(8), '사람이 할 일', h)
}
assert.deepEqual(humanWork(sets.measure), { approve: 64, choose: 34, find: 2 })
assert.deepEqual(humanWork(sets.p1), { approve: 33, choose: 29, find: 38 })
console.log('ok')
