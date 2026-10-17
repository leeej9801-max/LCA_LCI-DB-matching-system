// A21 작업 상태 mock. 실제 매칭은 하지 않고, 시작 시각에서 흐른 시간으로 단계를 진행시킨다 (약 4초 뒤 succeeded)
const STAGES = ['정규화', '후보 검색', '판정·환산']
const TOTAL_MS = 4000
const FAIL_MS = 2000 // fail 작업이 실패로 바뀌는 시각
const ROWS = 12 // 예시 세션의 행 수

const jobs = new Map()
let seq = 0

// instant: 샘플 BOM은 결과를 미리 계산해 둔 것으로 보고 처음부터 succeeded (spec/08 §7)
// fail: mock 전용, 이 작업은 FAIL_MS 뒤 failed
export const createJob = ({ instant, sessionId, fail }) => {
  const id = `job-${++seq}`
  jobs.set(id, { startedAt: Date.now(), instant, sessionId, fail })
  return id
}

const iso = (ms) => new Date(ms).toISOString()

// A21 GET /api/jobs/{job_id}
export const getJob = (id) => {
  const job = jobs.get(id)
  if (!job) return [404, { detail: '작업을 찾을 수 없습니다.' }]
  const t = job.instant ? TOTAL_MS : Date.now() - job.startedAt
  const per = TOTAL_MS / STAGES.length
  const stages = STAGES.map((name, i) => {
    const done = Math.round(Math.min(Math.max((t - i * per) / per, 0), 1) * ROWS)
    return {
      name, done, total: ROWS,
      state: done >= ROWS ? 'succeeded' : done > 0 ? 'running' : 'queued',
      started_at: done > 0 ? iso(job.startedAt + i * per) : null,
      finished_at: done >= ROWS ? iso(job.startedAt + (i + 1) * per) : null,
    }
  })
  if (job.fail && t >= FAIL_MS) {
    return [200, { job_id: id, kind: 'match', state: 'failed', stages, result: {}, error: { detail: '행을 정규화하는 중 오류가 발생했습니다.', code: 'MATCH_FAILED' } }]
  }
  const succeeded = t >= TOTAL_MS
  return [200, { job_id: id, kind: 'match', state: succeeded ? 'succeeded' : 'running', stages, result: succeeded ? { session_id: job.sessionId } : {} }]
}
