import { useEffect, useState } from 'react'
import { getEvalRun, listEvalRuns } from '@/api/eval'
import { isMock } from '@/api/client'
import DevInfo from '@/components/DevInfo'
import MockNotice from '@/components/MockNotice'
import Reason from '@/components/Reason'
import RunResult from './evaluation/RunResult'

const MOCK = import.meta.env.VITE_API_MOCK === '1'

const dateOf = (iso) => iso.slice(0, 10)

// S7 평가 (FR-901~903). 측정 기록 목록(A19) → 한 건의 결과(A14). 평가 실행(A13)은 서버 연결 뒤
const EvaluationPage = () => {
  const [runs, setRuns] = useState(null) // A19 items
  const [runId, setRunId] = useState('')
  const [run, setRun] = useState(null) // { id, data } A14. 고른 기록과 id가 다르면 아직 불러오는 중
  const [error, setError] = useState(null)

  useEffect(() => {
    let ignore = false
    listEvalRuns()
      .then(({ items }) => {
        if (ignore) return
        setRuns(items)
        setRunId((items.find((r) => r.status === 'done') ?? items[0])?.run_id ?? '')
      })
      .catch((e) => !ignore && setError(e.detail))
    return () => { ignore = true }
  }, [])

  const current = runs?.find((r) => r.run_id === runId)
  const done = current?.status === 'done'

  useEffect(() => {
    if (!runId || !done) return
    let ignore = false
    getEvalRun(runId)
      .then((data) => !ignore && setRun({ id: runId, data }))
      .catch((e) => !ignore && setError(e.detail))
    return () => { ignore = true }
  }, [runId, done])

  return (
    <>
      <div className="head">
        <h1>평가</h1>
        <p>정답셋으로 매칭 성능을 재고, 단계를 하나씩 더해 가며 개선폭을 확인합니다.</p>
      </div>

      <MockNotice path="/eval">예시 데이터입니다. 실제 측정 결과가 아닙니다.</MockNotice>

      {runs?.length === 0 && <p className="note">아직 측정한 기록이 없습니다. 정답셋으로 평가를 실행하면 여기에 결과가 쌓입니다.</p>}

      {runs?.length > 0 && (
        <div className="ev-pick">
          <select className="inp" aria-label="측정 기록" value={runId} onChange={(e) => { setRunId(e.target.value); setError(null) }}>
            {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.config_label} · {dateOf(r.created_at)}</option>)}
          </select>
          <Reason text="정답셋을 올려 측정하는 기능은 준비 중">
            <button type="button" className="btn" disabled>새로 측정</button>
          </Reason>
        </div>
      )}

      {error && <p className="err" role="alert">{error}</p>}
      {current && !done && <p>{current.status === 'failed' ? '측정에 실패했습니다' : '측정 중입니다'}</p>}
      {done && run?.id === runId && <RunResult run={run.data} example={isMock('/eval')} />}

      <DevInfo>
        <p className="note">S7 · FR-901~903 · MVP(표만)</p>
        {MOCK && <p className="note">mock: 예시 데이터입니다</p>}
        <table className="api">
          <tbody>
            <tr><td className="i">A19<b>+</b></td><td className="m">GET</td><td>{'/api/eval/runs'}</td></tr>
            <tr><td className="i">A14</td><td className="m">GET</td><td>{'/api/eval/runs/{id}'}</td></tr>
            <tr><td className="i">A13</td><td className="m">POST</td><td>{'/api/eval/runs'} · 화면 미연결</td></tr>
          </tbody>
        </table>
      </DevInfo>
    </>
  )
}

export default EvaluationPage
