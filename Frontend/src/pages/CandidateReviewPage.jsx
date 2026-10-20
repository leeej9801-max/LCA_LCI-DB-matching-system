import { useEffect, useRef, useState } from 'react'
import { useNavigate, useOutletContext, useParams } from 'react-router'
import Reason from '@/components/Reason'
import terms, { plainText } from '@/terms'
import DataQuality from './datasets/DataQuality'
import DatasetPicker from './datasets/DatasetPicker'
import CandidateTable from './results/CandidateTable'
import ConversionBox from './results/ConversionBox'
import { STATUS, attrParts, conversionDone } from './results/format'
import { rowStatus } from './results/status'

const MEMO_PLACEHOLDER = '대용으로 쓴 이유, 확인할 점'

const PanelBody = ({ row, update, explain, notify }) => {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [confirmVeto, setConfirmVeto] = useState(false)
  const [open, setOpen] = useState(null) // 접힌 영역: 'quality' | 'picker' | 'input' | null
  const [memo, setMemo] = useState(row.review.note ?? '')

  // 성공하면 true. 오류는 error 에 { detail, code, meta } 로 둔다: OUT_OF_RANGE 는 입력칸 옆에, CONVERSION_INCOMPLETE 는 결정 줄에 보인다
  const act = async (patch) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await update(row.id, patch)
      return true
    } catch (e) {
      setError(e)
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
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  // 열 클릭 = 고르기. 승인된 행의 선택을 바꾸면 서버가 승인을 푼다(A03). 그 사실을 알린다
  const choose = async (d) => {
    const released = row.review.status === 'approved' && d.dataset_id !== row.selected_id
    setConfirmVeto(false)
    if (!(await act({ selected_id: d.dataset_id }))) return false
    setNotice(released ? '선택을 바꿔 승인이 풀렸습니다. 다시 승인하세요.' : null)
    return true
  }

  const pickFromList = async (d) => {
    if (!(await choose(d))) return
    setOpen(null)
    requestAnimationFrame(() => document.getElementById('conv')?.scrollIntoView({ block: 'nearest' }))
  }

  const cands = row.candidates.slice(0, 3)
  const rank = cands.findIndex((c) => c.dataset_id === row.selected_id)
  const selCand = rank >= 0 ? cands[rank] : null
  const approved = row.review.status === 'approved'
  const name = row.clean.name || row.raw.name

  // 결정 한 줄. 승인 알림은 목록 화면(ResultsPage)이 3초 보여 주고 되돌리기를 받는다 — 패널을 닫거나 다른 행으로 가도 유지된다
  const decide = async (status, text) => {
    if (status === 'approved' && selCand?.veto && !confirmVeto) {
      setConfirmVeto(true)
      return
    }
    const prev = { review_status: row.review.status, note: row.review.note ?? '' }
    const noteChanged = memo !== prev.note
    const patch = { review_status: status, ...(noteChanged && { note: memo }) }
    if (!(await act(patch))) return
    setConfirmVeto(false)
    notify(`${text} · ${status === 'approved' ? row.selected.name : name}`, () => update(row.id, { review_status: prev.review_status, ...(noteChanged && { note: prev.note }) }))
  }

  const { raw, clean } = row
  const inputs = [
    ['품명', raw.name, clean.name],
    ['규격', raw.spec, clean.spec],
    ['단위', raw.unit, clean.unit_display],
    ['수량', raw.quantity, clean.quantity == null ? '' : String(clean.quantity)],
  ]
  const incomplete = error?.code === 'CONVERSION_INCOMPLETE'
  const approveOff = busy || !row.selected || approved || !conversionDone(row)
  const approveWhy = approved ? '이미 승인한 행입니다' : !row.selected ? '먼저 후보를 고르세요' : '단위 변환이 끝나야 승인할 수 있습니다'
  const toggle = (k) => setOpen(open === k ? null : k)

  return (
    <div className="u7-panel-body">
      {error && !['OUT_OF_RANGE', 'CONVERSION_INCOMPLETE'].includes(error.code) && <p className="err" role="alert">{error.detail}</p>}
      {notice && <p className="banner" role="status">{notice}</p>}

      <section className="u7-sec" aria-label="후보 비교">
        <div className="sec-h"><h3>후보 비교</h3><span>열을 눌러 고릅니다 · 같은 이름은 최신판만</span></div>
        {row.match_state === 'no_answer' && cands.length > 0 && (
          <p className="note-box" role="note">
            참고용 후보입니다. 근거가 약해 맞는 후보가 없다고 판단했습니다.
            {row.no_answer_reason && <span className="sub">{row.no_answer_reason}</span>}
          </p>
        )}
        {cands.length ? (
          <CandidateTable cands={cands} selectedId={row.selected_id} busy={busy} onPick={choose} />
        ) : (
          <p>맞는 후보가 없습니다. 아래 "목록에 없는 데이터셋 직접 선택"으로 고르세요.</p>
        )}
        <div className="links">
          {cands.length > 0 && <button type="button" className="link-btn" aria-expanded={open === 'quality'} onClick={() => toggle('quality')}>{open === 'quality' ? '▾' : '▸'} 데이터 품질 비교</button>}
          <button type="button" className="link-btn" aria-expanded={open === 'picker'} onClick={() => toggle('picker')}>목록에 없는 데이터셋 직접 선택</button>
          {row.selected && !row.explanation && <button type="button" className="link-btn" disabled={busy} onClick={askExplain}>근거 설명 보기</button>}
          <button type="button" className="link-btn" aria-expanded={open === 'input'} onClick={() => toggle('input')}>{open === 'input' ? '▾' : '▸'} 입력 상세</button>
        </div>

        {open === 'quality' && (
          <div className="q-grid" style={{ '--n': cands.length }}>
            {cands.map((c, i) => (
              <div key={c.dataset_id}><b>{i + 1}순위 {c.name}</b><DataQuality d={c} /></div>
            ))}
          </div>
        )}
        {open === 'picker' && <DatasetPicker initialQuery={row.normalized_name} busy={busy} onPick={pickFromList} onClose={() => setOpen(null)} />}
        {open === 'input' && (
          <div className="u7-box">
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
          </div>
        )}
        {row.explanation && (
          <div className="expl">
            <span className="lb">{row.explanation.source === 'rule' ? '규칙 기반 설명' : 'AI 생성 설명'}</span>
            <p>{plainText(row.explanation.text)}</p>
            {row.explanation.questions.length > 0 && <ul className="plain">{row.explanation.questions.map((q) => <li key={q}>{q}</li>)}</ul>}
          </div>
        )}
      </section>

      <div className="u7-two">
        <ConversionBox key={row.selected_id} row={row} busy={busy} error={error} onCheck={(patch) => act(patch)} />
        <section className="u7-box" aria-label="메모">
          <label className="box-h" htmlFor="memo">메모 <span className="opt">선택</span></label>
          <textarea id="memo" className="memo" value={memo} maxLength={200} placeholder={MEMO_PLACEHOLDER} onChange={(e) => setMemo(e.target.value)} />
        </section>
      </div>

      <div className="u7-decide">
        <span className="pick-label">
          선택 <b>{row.selected ? (selCand ? `${rank + 1}순위 ${row.selected.name}` : `직접 선택 ${row.selected.name}`) : '없음'}</b>
          {confirmVeto && <span className="warn-note"> · 차단 규칙을 무시합니다. 이력에 남습니다. 승인을 한 번 더 누르세요</span>}
          {incomplete && <span className="warn-note" role="alert"> · {error.detail}</span>}
        </span>
        <span className="decide-btns">
          <button type="button" className="btn" disabled={busy} onClick={() => decide('rejected', '반려했습니다')}>반려</button>
          <button type="button" className="btn" disabled={busy} onClick={() => decide('excluded', '제외했습니다')}>제외</button>
          <Reason when={approveOff && !busy} text={approveWhy}>
            <button type="button" className="btn pri" disabled={approveOff} onClick={() => decide('approved', '승인했습니다')}>
              {approved ? '승인됨' : confirmVeto ? '차단 무시하고 승인' : '승인'}
            </button>
          </Reason>
        </span>
      </div>
    </div>
  )
}

const isTyping = (el) => el instanceof HTMLElement && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable)

// S3 후보 비교 패널 (FR-801·802). S2 위에 열리는 오른쪽 패널(목록 위치 유지). 닫으면 S2로(탭·검색 유지).
// 키보드: ← → 이전·다음 행, Esc 닫기(입력칸에 글자를 쓰는 중에는 화살표를 가로채지 않는다)
const CandidateReviewPage = () => {
  const { rowId } = useParams()
  const { sessionId, rows, visibleIds, update, explain, search, notify } = useOutletContext()
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
    const onKey = (e) => {
      if (e.key === 'Escape') navigate(closeTo)
      else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && !isTyping(e.target)) {
        const to = e.key === 'ArrowLeft' ? prevId : nextId
        if (to != null) navigate(rowTo(to))
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- rowTo 는 sessionId·search 로만 정해진다
  }, [navigate, closeTo, prevId, nextId, sessionId, search])

  const status = row ? STATUS[rowStatus(row)][0] : null
  const name = row ? row.clean.name || row.raw.name : ''
  const qty = row ? row.clean.quantity ?? row.raw.quantity : null
  const roleText = row ? row.input_role ?? (row.inferred_role ? `${row.inferred_role}(이름에서 추정)` : '없음(전체에서 찾음)') : ''
  const sub = row ? [row.raw.spec && `규격 ${row.raw.spec}`, `수량 ${qty || '—'} ${row.clean.unit_display ?? row.raw.unit}`, `${terms.input_role.label} ${roleText}`].filter(Boolean).join(' · ') : ''

  return (
    <>
      <div className="u7-backdrop" aria-hidden="true" onClick={() => navigate(closeTo)} />
      <aside className="u7-panel" ref={panelRef} tabIndex={-1} role="dialog" aria-labelledby="cmp-title">
        <div className="u7-panel-head">
          <div>
            {row && <div className="pos">행 {rows.indexOf(row) + 1} / {rows.length} · {status}</div>}
            <h2 id="cmp-title">{row ? name : '후보 비교'}</h2>
            {row && <div className="sub">{sub}</div>}
          </div>
          <div className="pnav">
            <button type="button" className="sq" title="이전 행" aria-label="이전 행" disabled={prevId == null} onClick={() => navigate(rowTo(prevId))}>‹</button>
            <button type="button" className="sq" title="다음 행" aria-label="다음 행" disabled={nextId == null} onClick={() => navigate(rowTo(nextId))}>›</button>
            <button type="button" className="sq" title="닫기" aria-label="닫기" onClick={() => navigate(closeTo)}>✕</button>
          </div>
        </div>
        {row
          ? <PanelBody key={row.id} row={row} update={update} explain={explain} notify={notify} />
          : <div className="u7-panel-body"><p className="err">행을 찾을 수 없습니다.</p></div>}
      </aside>
    </>
  )
}

export default CandidateReviewPage
