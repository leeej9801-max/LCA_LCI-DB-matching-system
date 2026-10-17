import data from './data/eval.mock.json'

// A19 GET /api/eval/runs
export const listEvalRuns = () => [200, data.list]

// A14 GET /api/eval/runs/{id}
export const getEvalRun = (id) =>
  Object.hasOwn(data.runs, id) ? [200, data.runs[id]] : [404, { detail: '평가 기록을 찾을 수 없습니다.' }]
