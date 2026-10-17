import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useOutletContext, useParams } from 'react-router'
import DatasetPicker from './datasets/DatasetPicker'
import CandidateGrid from './results/CandidateGrid'
import ConversionBox from './results/ConversionBox'
import { attrParts } from './results/format'

const PanelBody = ({ row, update, explain, nextHref }) => {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const [confirmId, setConfirmId] = useState(null)
  const [picking, setPicking] = useState(false)
  const [note, setNote] = useState(row.review.note)

  // 성공하면 true. next: 배너에 "다음 행 →" 링크를 붙일지 (승인·반려·제외)
  const act = async (patch, doneText, next = true) => {
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      await update(row.id, patch)
      setDone(doneText && { text: doneText, next })
      setConfirmId(null)
      return true
    } catch (e) {
      setError(e.detail)
      return false
    } finally {
      setBusy(false)
    }
  }

  const askExplain = async () => {
    setBusy(true)
    setError(null)
    try {
      await explain(row.id)
    } catch (e) {
      setError(e.detail)
    } finally {
      setBusy(false)
    }
  }

  const pick = async (d) => {
    // 승인된 행의 선택을 바꾸면 서버가 승인을 푼다(A03). 그 사실을 알린다
    const released = row.review.status === 'approved' && d.dataset_id !== row.selected_id
    if (!(await act({ selected_id: d.dataset_id }, released ? '승인이 해제되었습니다. 다시 승인하세요.' : '선택을 바꿨습니다', false))) return
    setPicking(false)
    // 피커가 닫히면 환산 상태가 화면 안에 오도록
    requestAnimationFrame(() => document.getElementById('conv')?.scrollIntoView({ block: 'nearest' }))
  }

  const { raw, clean } = row
  const inputs = [
    ['품명', raw.name, clean.name],
    ['규격', raw.spec, clean.spec],
    ['단위', raw.unit, clean.unit_display],
    ['수량', raw.quantity, clean.quantity == null ? '' : String(clean.quantity)],
  ]
  const cands = row.candidates.slice(0, 3)
  const approved = row.review.status === 'approved'
  const pickButton = <button type="button" className={cands.length ? 'btn' : 'btn lg'} onClick={() => setPicking(true)}>직접 선택</button>

  return (
    <div className="panel-body">
      {done && (
        <p className="banner" role="status">
          {done.text}{done.next && nextHref && <> · <Link to={nextHref}>다음 행 →</Link></>}
        </p>
      )}
      {approved && !done && <p className="banner">승인됨: {row.selected.name} · 변경하려면 다른 후보 승인</p>}

      <section className="sec">
        <h3>입력</h3>
        <dl className="kv">
          {inputs.map(([label, rawValue, cleanValue]) => (
            <div className="kv-row" key={label}>
              <dt>{label}</dt>
              <dd>{rawValue || '—'}{rawValue !== cleanValue && <span className="sub">정제: {cleanValue || '—'}</span>}</dd>
            </div>
          ))}
          {Object.entries(row.attrs).map((e) => {
            const [k, v] = attrParts(e)
            return <div className="kv-row" key={e[0]}><dt>{k}</dt><dd>{v}</dd></div>
          })}
          {row.synonym_hits.length > 0 && <div className="kv-row"><dt>사전 적용</dt><dd>{row.synonym_hits.join(', ')}</dd></div>}
          {row.issues.length > 0 && <div className="kv-row"><dt>확인 사항</dt><dd>{row.issues.join(' / ')}</dd></div>}
        </dl>
      </section>

      <section className="sec">
        <h3>후보 비교</h3>
        {cands.length ? (
          <CandidateGrid
            cands={cands}
            selectedId={row.selected_id}
            busy={busy}
            confirmId={confirmId}
            setConfirmId={setConfirmId}
            onApprove={(c) => act({ selected_id: c.dataset_id, review_status: 'approved' }, '승인했습니다')}
          />
        ) : (
          <>
            <p>일치하는 후보 없음.</p>
            {!picking && <div>{pickButton}</div>}
          </>
        )}
        {row.selected && !row.explanation && <div><button type="button" className="btn sm" disabled={busy} onClick={askExplain}>근거 설명 보기</button></div>}
        {row.explanation && (
          <div className="expl">
            <span className="lb">{row.explanation.source === 'rule' ? '규칙 기반 설명' : 'AI 생성 설명'}</span>
            <p>{row.explanation.text}</p>
            {row.explanation.questions.length > 0 && <ul className="plain">{row.explanation.questions.map((q) => <li key={q}>{q}</li>)}</ul>}
          </div>
        )}
      </section>

      <ConversionBox
        key={row.selected_id}
        row={row}
        busy={busy}
        error={error}
        onCheck={(patch) => act(patch, null)}
        onApprove={() => act({ review_status: 'approved' }, '승인했습니다')}
      />

      {(cands.length > 0 || picking) && (
        <section className="sec">
          {!picking && <div>{pickButton}</div>}
          {picking && <DatasetPicker initialQuery={row.normalized_name} busy={busy} onPick={pick} onClose={() => setPicking(false)} />}
        </section>
      )}

      <section className="sec">
        <label className="lb" htmlFor="note">메모 (선택)</label>
        <input id="note" className="inp" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
        <div className="flex-row">
          <button type="button" className="btn" disabled={busy} onClick={() => act({ review_status: 'rejected', note }, '반려했습니다')}>반려</button>
          <button type="button" className="btn" disabled={busy} onClick={() => act({ review_status: 'excluded', note }, '제외했습니다')}>제외</button>
        </div>
      </section>
    </div>
  )
}

// S3 후보 비교 패널 (FR-801·802). S2 위에 열리는 오른쪽 패널. 닫으면 S2로(탭·검색 유지)
const CandidateReviewPage = () => {
  const { rowId } = useParams()
  const { sessionId, rows, visibleIds, update, explain, search } = useOutletContext()
  const navigate = useNavigate()
  const panelRef = useRef(null)

  const id = Number(rowId)
  const row = rows.find((r) => r.id === id)
  const closeTo = `/results/${sessionId}${search}`
  const rowTo = (to) => `/results/${sessionId}/rows/${to}${search}`
  // 현재 행이 목록에서 빠져도(승인해서 탭을 떠남) 원래 순서상 이전·다음 행을 찾는다
  const prevId = visibleIds.findLast((x) => x < id)
  const nextId = visibleIds.find((x) => x > id)

  useEffect(() => { panelRef.current.focus() }, [rowId])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && navigate(closeTo)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navigate, closeTo])

  return (
    <aside className="panel wide" ref={panelRef} tabIndex={-1} role="dialog" aria-labelledby="cmp-title">
      <div className="panel-head">
        <div>
          <h2 id="cmp-title">후보 비교</h2>
          {row && <span className="sub">{row.clean.name || row.raw.name}</span>}
        </div>
        <div className="panel-nav">
          <button type="button" className="text-btn" disabled={prevId == null} onClick={() => navigate(rowTo(prevId))}>이전 행</button>
          <button type="button" className="text-btn" disabled={nextId == null} onClick={() => navigate(rowTo(nextId))}>다음 행</button>
          <button type="button" className="text-btn" onClick={() => navigate(closeTo)}>닫기</button>
        </div>
      </div>
      {row
        ? <PanelBody key={row.id} row={row} update={update} explain={explain} nextHref={nextId == null ? null : rowTo(nextId)} />
        : <div className="panel-body"><p className="err">행을 찾을 수 없습니다.</p></div>}
    </aside>
  )
}

export default CandidateReviewPage
