import { useCallback, useEffect, useState } from 'react'
import { getEvalRun, listEvalRuns } from '@/api/eval'
import { isMock } from '@/api/client'
import DevInfo from '@/components/DevInfo'
import terms from '@/terms'
import '@styles/eval.css'
import EvalAside from './evaluation/EvalAside'
import EvalDashboard from './evaluation/EvalDashboard'
import MyBomTab from './evaluation/MyBomTab'
import { BULK_NOTE, EVAL_HEAD_SUB, MINE_HEAD_SUB, SPEC_NOTE, TOTAL_DATASETS } from './evaluation/evalText'
import { compareGoldId, pick } from './evaluation/pick'

const dateOf = (iso) => iso.slice(0, 10).replaceAll('-', '.')

// S7 성능 확인 (FR-901~903). 탭 1 = 내가 올린 BOM(A02), 탭 2·3 = 정답을 아는 시험 결과(A19 목록과 A14 기록).
// 평가 기록은 한 번에 불러오되, 실패해도 탭 1은 그대로 쓴다. 평가 실행(A13)은 서버 연결 뒤
const EvaluationPage = () => {
  const [tab, setTab] = useState(terms.eval_tabs[0].key)
  const [state, setState] = useState({ status: 'loading' }) // loading | error | done
  const [attempt, setAttempt] = useState(0)

  const load = useCallback(() => {
    let ignore = false
    listEvalRuns()
      .then(async ({ items }) => {
        const picks = Object.fromEntries(await Promise.all(items.map((i) => getEvalRun(i.run_id).then((r) => [i.run_id, pick(r)]))))
        if (!ignore) setState({ status: 'done', items, picks })
      })
      .catch((e) => !ignore && setState({ status: 'error', detail: e.detail ?? e.message }))
    return () => { ignore = true }
  }, [])

  useEffect(() => load(), [load, attempt])

  const { items, picks } = state
  const itemOf = (goldId) => items?.find((i) => picks[i.run_id].goldId === goldId)
  const current = terms.eval_tabs.find((t) => t.key === tab)
  const sel = current.goldId && itemOf(current.goldId)
  const cmpItem = sel && itemOf(compareGoldId(current.goldId))
  const p1Item = itemOf('gold-p1-v1')
  const onMine = tab === 'mine'

  return (
    <div className="pf">
      <div className="pf-body">
        <div className="pf-main">
          <div className="pf-head">
            <div>
              <h1>성능 확인</h1>
              <p>{onMine ? MINE_HEAD_SUB : EVAL_HEAD_SUB}</p>
            </div>
            {sel && <p className="pf-date">{dateOf(sel.created_at)} 측정 · 국가 LCI DB {TOTAL_DATASETS}건</p>}
          </div>

          <div className="pf-tabs" role="group" aria-label="데이터 고르기">
            {terms.eval_tabs.map((t) => {
              const item = t.goldId && itemOf(t.goldId)
              return (
                <button key={t.key} type="button" aria-pressed={t.key === tab} onClick={() => setTab(t.key)}>
                  {t.label}{item && <span>{item.rows}개</span>}
                </button>
              )
            })}
          </div>

          {onMine && <MyBomTab />}

          {!onMine && state.status === 'loading' && <p role="status">시험 결과를 불러오는 중입니다…</p>}
          {!onMine && state.status === 'error' && (
            <p className="err" role="alert">
              {import.meta.env.DEV
                ? `시험 결과를 불러오지 못했습니다. 서버가 켜져 있는지 확인한 뒤 다시 시도해 주세요. (${state.detail})`
                : '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'}{' '}
              <button type="button" className="text-btn" onClick={() => { setState({ status: 'loading' }); setAttempt((n) => n + 1) }}>다시 시도</button>
            </p>
          )}
          {!onMine && state.status === 'done' && !sel && <p className="pf-empty">아직 측정 전입니다(최종 평가를 돌리면 여기에 나타납니다).</p>}

          {sel && p1Item && (
            <>
              <EvalDashboard
                key={sel.run_id} sel={picks[sel.run_id]} cmp={cmpItem && picks[cmpItem.run_id]} selName={current.label}
                cmpName={cmpItem && terms.eval_tabs.find((t) => t.goldId === picks[cmpItem.run_id].goldId).label} p1={picks[p1Item.run_id]} kind={current.key}
              />
              <p className="pf-source">
                수치: {dateOf(sel.created_at).replace('.', '년 ').replace('.', '월 ')}일 측정 · 규칙은 측정 전에 고정 · 데이터마다 한 번씩만 실행
                {current.key === 'bulk' && <><br />{BULK_NOTE}</>}
                <br />{SPEC_NOTE}
              </p>
            </>
          )}

          <DevInfo>
            <p className="note">S7 · FR-901~903 · {isMock('/eval') ? 'mock: 최종 평가 리포트 사본' : '실제 서버'}</p>
            {sel && <p className="note">기록 {sel.run_id} · 조합 {sel.config_label}</p>}
            <table className="api">
              <tbody>
                <tr><td className="i">A02</td><td className="m">GET</td><td>{'/api/sessions/{id}'} · 탭 1</td></tr>
                <tr><td className="i">A19<b>+</b></td><td className="m">GET</td><td>{'/api/eval/runs'}</td></tr>
                <tr><td className="i">A14</td><td className="m">GET</td><td>{'/api/eval/runs/{id}'}</td></tr>
                <tr><td className="i">A13</td><td className="m">POST</td><td>{'/api/eval/runs'} · 화면 미연결</td></tr>
              </tbody>
            </table>
          </DevInfo>
        </div>

        <EvalAside tab={tab} />
      </div>
    </div>
  )
}

export default EvaluationPage
