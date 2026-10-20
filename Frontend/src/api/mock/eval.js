// 최종 평가 리포트 세 개(Backend/app/data/eval_reports 와 같은 파일, 가공 없음)를 그대로 쓴다.
// 운영 빌드에 크기가 큰 JSON이 섞이지 않도록 요청 때 불러온다
const loaders = import.meta.glob('./data/eval/*.json', { import: 'default' })
const loadOf = (run_id) => loaders[`./data/eval/${run_id}.json`]
const ids = Object.keys(loaders).map((path) => path.split('/').pop().replace(/\.json$/, ''))

// 서버(app/api/evaluation.py)와 같은 이름·순서. 표에 없는 파일(튜닝용·110행)은 목록에서 뺀다. 파일이 없는 세트는 목록에서 빠질 뿐이다. 상세(A14)는 파일이 있으면 읽는다
const SET_LABELS = [['gold-bulk-v1', '가상 BOM 2000 (검증용)'], ['gold-p1-v1', '공개 문서 표기']]
const RUN_ID = /^eval-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-/

// A19 GET /api/eval/runs
export const listEvalRuns = async () => {
  const items = []
  for (const [key, set_label] of SET_LABELS) {
    for (const run_id of ids.filter((id) => id.includes(key) && RUN_ID.test(id))) {
      const r = await loadOf(run_id)()
      const [, y, mo, d, h, mi, s] = run_id.match(RUN_ID)
      items.push({
        run_id, status: 'done', created_at: `${y}-${mo}-${d}T${h}:${mi}:${s}`,
        config_label: r.config.head_case, set_label, split: r.config.split, rows: r.gold_stats.total,
      })
    }
  }
  return [200, { items, total: items.length }]
}

// A14 GET /api/eval/runs/{id}
export const getEvalRun = async (id) =>
  ids.includes(id) && RUN_ID.test(id) ? [200, await loadOf(id)()] : [404, { detail: '평가 기록을 찾을 수 없습니다.', code: 'EVAL_RUN_NOT_FOUND' }]
