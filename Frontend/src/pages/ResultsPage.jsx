import { Fragment, useEffect, useRef, useState } from 'react'
import { Link, Navigate, Outlet, useMatch, useNavigate, useParams, useSearchParams } from 'react-router'
import { isMock } from '@/api/client'
import { exportSession, explainRow, getSession, updateRow } from '@/api/sessions'
import ConfBar from '@/components/ConfBar'
import DevInfo from '@/components/DevInfo'
import MockNotice from '@/components/MockNotice'
import Reason from '@/components/Reason'
import TermsHelp from '@/components/TermsHelp'
import { sameName } from '@/terms'
import { rememberSession } from './evaluation/recentSessions'
import { STATUS, TABS, bulkBlock, groupByPart, orgYearRole, unitCell } from './results/format'
import { rowStatus } from './results/status'
import SummaryStrip from './results/SummaryStrip'

const PAGE_SIZE = 20
const HELP_TERMS = ['candidate', 'confidence', 'no_match', 'approved', 'rejected', 'excluded', 'conversion', 'duplicate_group', 'input_role', 'dataset_role', 'combined']
const TOAST_MS = 3000

// 추천 칸: 현재 선택(기본 선택은 1순위). 맞는 후보 없음·차단 행은 직접 고르기 전까지 "맞는 후보 없음"과 참고 후보 한 줄
const recommendation = (row, status) => {
  const none = (status === 'no_answer' || status === 'vetoed') && !row.selected?.manual
  if (none || !row.selected) {
    const ref = row.candidates[0]?.name
    return { title: row.candidates.length || none ? '맞는 후보 없음' : '선택한 데이터셋 없음', dim: true, sub: ref ? `참고 후보: ${ref}` : null }
  }
  const cand = row.candidates.find((c) => c.dataset_id === row.selected_id)
  return { title: row.selected.name, dim: false, sub: cand ? orgYearRole(cand) : [row.selected.category, row.selected.role].filter(Boolean).join(' · '), dup: cand?.duplicate_group?.size }
}

const Check = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#4ADE80" strokeWidth="2.4" aria-hidden="true"><path d="M5 12.5 10 17l9-10" /></svg>
)

// "승인분 내보내기 ▾": 형식을 고르는 작은 메뉴. 바깥을 누르거나 Esc 로 닫는다 (A07)
const ExportMenu = ({ disabled, mock, onPick }) => {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)
  const btn = useRef(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e) => !wrap.current.contains(e.target) && setOpen(false)
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      btn.current.focus()
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  const items = mock ? [['csv', 'CSV (예시 데이터)']] : [['xlsx', '엑셀 (.xlsx)'], ['csv', 'CSV']]
  return (
    <span className="dd-wrap" ref={wrap}>
      <button ref={btn} type="button" className="btn pri" disabled={disabled} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        승인분 내보내기 <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="dd-menu" role="menu">
          {items.map(([format, label]) => (
            <li key={format} role="none"><button type="button" role="menuitem" onClick={() => { setOpen(false); onPick(format) }}>{label}</button></li>
          ))}
        </ul>
      )}
    </span>
  )
}

// S2 결과 검토 (FR-801). 탭·검색·쪽은 URL 쿼리, 상세(S3)는 자식 라우트의 패널
const ResultsPage = () => {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState({ key: null })
  const [selection, setSelection] = useState({ tab: null, ids: [] })
  const [bulk, setBulk] = useState({ busy: false, report: null })
  const [exportMsg, setExportMsg] = useState(null)
  const [toast, setToast] = useState(null) // { id, text, undo? } 승인 뒤 3초 알림

  const key = `${sessionId}#${reload}`
  const tab = TABS.find((t) => t.key === searchParams.get('tab')) ?? TABS[0]
  const q = searchParams.get('q') ?? ''
  const offset = Math.max(Number(searchParams.get('offset')) || 0, 0)
  const openId = useMatch('/results/:sessionId/rows/:rowId')?.params.rowId

  useEffect(() => {
    const requestKey = `${sessionId}#${reload}`
    let ignore = false
    getSession(sessionId)
      .then((data) => {
        if (ignore) return
        setResult({ key: requestKey, data })
        rememberSession({ id: sessionId, filename: data.filename, total: data.summary.total }) // 성능 확인 "내가 올린 BOM" 탭의 작업 목록
      })
      .catch((error) => !ignore && setResult({ key: requestKey, error }))
    return () => { ignore = true }
  }, [sessionId, reload])

  // 패널을 닫으면 마지막으로 보던 행으로 포커스를 돌려준다 (그 행이 목록에서 빠졌으면 첫 행)
  const lastOpen = useRef(null)
  useEffect(() => {
    if (openId) {
      lastOpen.current = openId
      return
    }
    if (!lastOpen.current) return
    const el = document.querySelector(`[data-open="${lastOpen.current}"]`) ?? document.querySelector('[data-open]')
    el?.focus()
    lastOpen.current = null
  }, [openId])

  // 알림은 3초 뒤에 저절로 사라진다. 닫기 버튼은 없다
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), TOAST_MS)
    return () => clearTimeout(t)
  }, [toast])

  const loading = result.key !== key
  const data = loading ? null : result.data
  const rows = data?.rows ?? []

  const statusMap = new Map(rows.map((r) => [r.id, rowStatus(r)]))
  const statusOf = (r) => statusMap.get(r.id)
  const count = (states) => rows.filter((r) => !states || states.includes(statusOf(r))).length
  const needle = q.trim().toLowerCase()
  const visible = rows.filter((r) =>
    (!tab.states || tab.states.includes(statusOf(r))) &&
    (!needle || [r.raw.name, r.clean.name, r.normalized_name, r.raw.spec].some((s) => s?.toLowerCase().includes(needle))))
  const visibleIds = visible.map((r) => r.id)
  const lastOffset = visible.length ? Math.floor((visible.length - 1) / PAGE_SIZE) * PAGE_SIZE : 0
  const start = Math.min(offset, lastOffset)
  const pageRows = visible.slice(start, start + PAGE_SIZE)

  const setParam = (changes) => {
    const next = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('offset' in changes)) next.delete('offset') // 조건이 바뀌면 첫 쪽으로
    setSearchParams(next)
  }

  // A03 응답의 row·summary로 로컬 상태를 갱신한다
  const update = async (rowId, patch) => {
    const res = await updateRow(sessionId, rowId, patch)
    setResult((r) => ({ ...r, data: { ...r.data, summary: res.summary, rows: r.data.rows.map((x) => (x.id === res.row.id ? res.row : x)) } }))
    return res.row
  }

  // A04: 근거 설명은 행에 붙여 둔다 (선택·상태가 바뀌면 A03 응답에서 null로 돌아온다)
  const explain = async (rowId) => {
    const explanation = await explainRow(sessionId, rowId)
    setResult((r) => ({ ...r, data: { ...r.data, rows: r.data.rows.map((x) => (x.id === rowId ? { ...x, explanation } : x)) } }))
  }

  // 결정(승인·반려·제외) 뒤 알림. undo 는 직전 결정 하나를 취소해 상태를 되돌린다
  const notify = (text, undo) => setToast({ id: Date.now(), text, undo })
  const undoNow = async () => {
    const undo = toast.undo
    try {
      await undo()
      setToast({ id: Date.now(), text: '되돌렸습니다' })
    } catch (e) {
      setToast({ id: Date.now(), text: `되돌리지 못했습니다 · ${e.detail}` })
    }
  }

  // A07: 기본 xlsx, csv 는 선택. mock 은 csv 만 낸다(형식을 가리지 않는다)
  const download = async (format) => {
    setExportMsg(null)
    try {
      const { blob, filename } = await exportSession(sessionId, format)
      const url = URL.createObjectURL(blob)
      Object.assign(document.createElement('a'), { href: url, download: filename ?? `결과_${sessionId}.${format}` }).click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setExportMsg(e.code === 'NO_APPROVED_ROWS' ? '승인한 행이 없습니다. 행을 승인한 뒤 내보내 주세요.' : e.detail)
    }
  }
  const EXPORT_MOCK = isMock('/sessions')

  const selectedIds = selection.tab === tab.key ? selection.ids : []
  const toggleSelect = (id) =>
    setSelection({ tab: tab.key, ids: selectedIds.includes(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id] })

  const approveSelected = async () => {
    setBulk({ busy: true, report: null })
    let ok = 0
    const failed = []
    for (const id of selectedIds) {
      const row = rows.find((r) => r.id === id)
      try {
        await update(id, { selected_id: row.selected_id, review_status: 'approved' })
        ok += 1
      } catch (e) {
        failed.push({ name: row.clean.name || row.raw.name, detail: e.detail })
      }
    }
    setSelection({ tab: tab.key, ids: [] })
    setBulk({ busy: false, report: { ok, failed } })
  }

  // 탭 줄에서 ←→(Home·End)로 이웃 탭 버튼에 포커스를 옮긴다. 누르기는 Enter·Space 그대로
  const moveTab = (e) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key]
    const btns = [...e.currentTarget.querySelectorAll('.tab')]
    const at = btns.indexOf(document.activeElement)
    if (at < 0 || (!step && e.key !== 'Home' && e.key !== 'End')) return
    e.preventDefault()
    btns[e.key === 'Home' ? 0 : e.key === 'End' ? btns.length - 1 : (at + step + btns.length) % btns.length].focus()
  }

  const search = searchParams.toString() ? `?${searchParams}` : ''
  const openRow = (row) => navigate(`/results/${sessionId}/rows/${row.id}${search}`)
  const grouped = rows.some((r) => r.part_no) // 부품번호가 있는 세션만 묶는다(없으면 평평한 표)
  const groups = grouped ? groupByPart(pageRows, rows) : [{ key: 'all', rows: pageRows }]
  const columns = 7

  return (
    <div className="u7">
      <div className="u7-head">
        <div>
          <h1>결과 검토 및 승인 처리</h1>
          <p className="meta">{data ? `${data.filename} · ${data.rows.length}행` : ' '}</p>
        </div>
        <div className="u7-actions">
          <Link className="btn" to="/upload">다시 업로드</Link>
          <ExportMenu disabled={!data} mock={EXPORT_MOCK} onPick={download} />
        </div>
      </div>
      {exportMsg && <p className="err" role="alert">{exportMsg}</p>}

      <MockNotice path="/sessions" />

      {result.error && !loading ? (
        result.error.code === 'JOB_NOT_FINISHED' && result.error.meta?.job_id ? (
          <Navigate to={`/upload?job=${encodeURIComponent(result.error.meta.job_id)}`} replace /> // 아직 매칭 중: 진행 화면으로
        ) : result.error.code === 'SESSION_NOT_FOUND' ? (
          <div className="state">
            <p className="err">세션이 없거나 만료되었습니다(업로드 후 24시간).</p>
            <Link className="btn" to="/upload">업로드로 가기</Link>
          </div>
        ) : result.error.code === 'JOB_FAILED' ? (
          <div className="state">
            <p className="err">{result.error.detail}</p>
            <Link className="btn" to="/upload">다시 업로드</Link>
          </div>
        ) : (
          <div className="state">
            <p className="err">오류 {result.error.status ?? '—'}: {result.error.detail}</p>
            <button type="button" className="text-btn" onClick={() => setReload((n) => n + 1)}>다시 시도</button>
          </div>
        )
      ) : loading ? (
        <div className="summary">불러오는 중</div>
      ) : (
        <>
          <SummaryStrip rows={rows} statusOf={statusOf} />

          <div className="u7-card">
            <div className="u7-toolbar">
              <div className="tabs" role="group" aria-label="보기" onKeyDown={moveTab}>
                {TABS.map((t) => (
                  <button key={t.key} type="button" className="tab" aria-pressed={t.key === tab.key} onClick={() => setParam({ tab: t.key === TABS[0].key ? '' : t.key })}>
                    {t.label}<span className="num">{count(t.states)}</span>
                  </button>
                ))}
              </div>
              <div className="u7-tools">
                <form
                  className="search-box"
                  role="search"
                  onSubmit={(e) => {
                    e.preventDefault()
                    setParam({ q: e.currentTarget.elements.q.value.trim() })
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
                  {/* key: 뒤로가기로 q가 바뀌면 입력칸도 맞춘다. Enter 로 검색 */}
                  <input name="q" aria-label="품명 검색" placeholder="품명 검색" key={q} defaultValue={q} maxLength={100} />
                </form>
                <TermsHelp keys={HELP_TERMS} />
              </div>
            </div>

            {(selectedIds.length > 0 || bulk.report) && (
              <div className="bulk" aria-live="polite">
                {selectedIds.length > 0 && (
                  <button type="button" className="btn pri" disabled={bulk.busy} onClick={approveSelected}>
                    선택 {selectedIds.length}건 승인
                  </button>
                )}
                {bulk.report && (
                  <div>
                    <span>{bulk.report.ok}건 승인{bulk.report.failed.length > 0 && ` · ${bulk.report.failed.length}건 실패`}</span>
                    {bulk.report.failed.length > 0 && (
                      <ul className="err-list">{bulk.report.failed.map((f) => <li key={f.name}>{f.name}: {f.detail}</li>)}</ul>
                    )}
                  </div>
                )}
              </div>
            )}

            {visible.length === 0 ? (
              <div className="state"><p>이 탭에 해당하는 행이 없습니다.</p></div>
            ) : (
              <div className="tbl-scroll"><table className="u7-tbl rows">
                <colgroup><col className="w-chk" /><col /><col /><col className="w-conf" /><col className="w-unit" /><col className="w-st" /><col className="w-go" /></colgroup>
                <thead>
                  <tr>
                    <th><span className="visually-hidden">선택</span></th>
                    <th>입력</th><th>추천 데이터셋</th><th>신뢰도</th><th>단위</th><th>상태</th>
                    <th><span className="visually-hidden">열기</span></th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((g) => (
                    <Fragment key={g.key}>
                      {grouped && (
                        <tr className="grp">
                          <th colSpan={columns} scope="colgroup">
                            {g.part_no ? <>부품번호 {g.part_no} · {g.title}</> : '부품번호 없음'}
                            {g.warn && <span className="grp-warn"> · 가공이 두 번 계산될 수 있음</span>}
                          </th>
                        </tr>
                      )}
                      {g.rows.map((row) => {
                        const status = statusOf(row)
                        const [label, tone] = STATUS[status]
                        const rec = recommendation(row, status)
                        const unit = unitCell(row)
                        const blocked = status === 'review' ? bulkBlock(row) : 'x'
                        const rowName = row.clean.name || row.raw.name
                        const qty = row.clean.quantity ?? row.raw.quantity
                        const level = row.selected?.confidence ?? row.candidates[0]?.confidence
                        return (
                          <tr
                            key={row.id}
                            data-open={row.id}
                            tabIndex={0}
                            className={String(row.id) === openId ? 'sel' : undefined}
                            onClick={() => openRow(row)}
                            onKeyDown={(e) => {
                              if (e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return
                              e.preventDefault()
                              openRow(row)
                            }}
                          >
                            <td className="c-chk" onClick={(e) => e.stopPropagation()}>
                              {status === 'review' && (
                                <Reason when={blocked != null} text={`일괄 승인할 수 없는 행: ${blocked}`}>
                                  <input
                                    type="checkbox"
                                    aria-label={`${rowName} 선택`}
                                    disabled={blocked != null || bulk.busy}
                                    checked={selectedIds.includes(row.id)}
                                    onChange={() => toggleSelect(row.id)}
                                  />
                                </Reason>
                              )}
                            </td>
                            <td className="c-in">
                              <b className="ell">{rowName}</b>
                              <span className="sub ell">{[row.raw.spec, `${qty || '—'} ${row.clean.unit_display ?? row.raw.unit}`].filter(Boolean).join(' · ')}</span>
                            </td>
                            <td className="c-cand">
                              <span className={rec.dim ? 'ell dim' : 'ell'}>{rec.title}{rec.dup > 1 && <span className="dup">{sameName(rec.dup)}</span>}</span>
                              {rec.sub && <span className="sub ell">{rec.sub}</span>}
                            </td>
                            <td><ConfBar level={level} /></td>
                            <td className={unit.warn ? 'unit warn' : 'unit'}>
                              {unit.warn && (
                                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true"><path d="M12 3 2 21h20L12 3z" /><path d="M12 10v5M12 18v.5" /></svg>
                              )}
                              {unit.text}
                            </td>
                            <td><span className={`chip ${tone}`}>{label}</span></td>
                            <td className="go" aria-hidden="true">›</td>
                          </tr>
                        )
                      })}
                    </Fragment>
                  ))}
                </tbody>
              </table></div>
            )}

            {visible.length > 0 && (
              <nav className="u7-pager" aria-label="페이지">
                <span className="num">{start + 1}–{Math.min(start + PAGE_SIZE, visible.length)} / {visible.length}행</span>
                <span>
                  <button type="button" className="text-btn" disabled={start === 0} onClick={() => setParam({ offset: start > PAGE_SIZE ? String(start - PAGE_SIZE) : '' })}>‹ 이전</button>
                  <span aria-hidden="true"> · </span>
                  <button type="button" className="text-btn" disabled={start + PAGE_SIZE >= visible.length} onClick={() => setParam({ offset: String(start + PAGE_SIZE) })}>다음 ›</button>
                </span>
              </nav>
            )}
          </div>
        </>
      )}

      {data && <Outlet context={{ sessionId, rows, visibleIds, update, explain, search, notify }} />}

      {toast && (
        <div className="u7-toast" role="status">
          <Check />
          <span>{toast.text}</span>
          {toast.undo && <button type="button" onClick={undoNow}>되돌리기</button>}
        </div>
      )}

      <DevInfo>
        <p className="note">S2 · S3 · FR-801</p>
        <table className="api">
          <tbody>
            <tr><td className="i">A02</td><td className="m">GET</td><td>{'/api/sessions/{id}'}</td></tr>
            <tr><td className="i">A03</td><td className="m">PATCH</td><td>{'/api/sessions/{id}/rows/{row}'}</td></tr>
            <tr><td className="i">A04</td><td className="m">POST</td><td>{'/api/sessions/{id}/rows/{row}/explain'}</td></tr>
            <tr><td className="i">A05</td><td className="m">GET</td><td>{'/api/datasets?q=&category=&has_xml=&sort=&limit=&offset= (직접 선택)'}</td></tr>
            <tr><td className="i">A07</td><td className="m">GET</td><td>{'/api/sessions/{id}/export?format=xlsx'}</td></tr>
          </tbody>
        </table>
      </DevInfo>
    </div>
  )
}

export default ResultsPage
