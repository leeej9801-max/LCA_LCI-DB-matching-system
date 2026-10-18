import { Fragment, useEffect, useRef, useState } from 'react'
import { Link, Navigate, Outlet, useMatch, useParams, useSearchParams } from 'react-router'
import { isMock } from '@/api/client'
import { exportSession, explainRow, getSession, updateRow } from '@/api/sessions'
import DevInfo from '@/components/DevInfo'
import Info from '@/components/Info'
import MockNotice from '@/components/MockNotice'
import Reason from '@/components/Reason'
import terms, { sameName } from '@/terms'
import { orgYearVersion } from './datasets/format'
import { STATUS, TABS, attrLine, bulkBlock, conversionHint, conversionLabel, groupByPart, isClose } from './results/format'
import { rowStatus } from './results/status'

const BAR = { approved: 'ok', review: 'warn', vetoed: 'block', no_answer: 'none', rejected: 'none', excluded: 'none' }

// 현재 선택(기본 선택은 1순위)이 있으면 {sel, cand}, 없으면 안내 글자. cand는 후보 안의 같은 데이터셋(직접 선택이면 없음)
const currentText = (row) => {
  if (row.selected) return { sel: row.selected, cand: row.candidates.find((c) => c.dataset_id === row.selected_id) }
  if (!row.candidates.length) return '일치 후보 없음'
  if (row.match_state === 'vetoed') return `후보 모두 차단 (${[...new Set(row.candidates.map((c) => c.veto?.rule_id))].join(', ')})`
  return '선택 없음'
}

// S2 결과 검토 (FR-801). 탭·검색은 URL 쿼리, 상세(S3)는 자식 라우트의 패널
const ResultsPage = () => {
  const { sessionId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState({ key: null })
  const [selection, setSelection] = useState({ tab: null, ids: [] })
  const [bulk, setBulk] = useState({ busy: false, report: null })
  const [exportMsg, setExportMsg] = useState(null)

  const key = `${sessionId}#${reload}`
  const tab = TABS.find((t) => t.key === searchParams.get('tab')) ?? TABS[0]
  const q = searchParams.get('q') ?? ''
  const openId = useMatch('/results/:sessionId/rows/:rowId')?.params.rowId

  useEffect(() => {
    const requestKey = `${sessionId}#${reload}`
    let ignore = false
    getSession(sessionId)
      .then((data) => !ignore && setResult({ key: requestKey, data }))
      .catch((error) => !ignore && setResult({ key: requestKey, error }))
    return () => { ignore = true }
  }, [sessionId, reload])

  // 패널을 닫으면 마지막으로 보던 행의 버튼으로 포커스를 돌려준다 (그 행이 목록에서 빠졌으면 첫 행)
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

  const loading = result.key !== key
  const data = loading ? null : result.data
  const rows = data?.rows ?? []

  const statusOf = new Map(rows.map((r) => [r.id, rowStatus(r)]))
  const count = (states) => rows.filter((r) => !states || states.includes(statusOf.get(r.id))).length
  const needle = q.trim().toLowerCase()
  const visible = rows.filter((r) =>
    (!tab.states || tab.states.includes(statusOf.get(r.id))) &&
    (!needle || [r.raw.name, r.clean.name, r.normalized_name, r.raw.spec].some((s) => s?.toLowerCase().includes(needle))))
  const visibleIds = visible.map((r) => r.id)

  const setParam = (changes) => {
    const next = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
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

  const search = searchParams.toString() ? `?${searchParams}` : ''
  const nonZero = ['approved', 'review', 'vetoed', 'no_answer', 'rejected', 'excluded'].filter((s) => s === 'approved' || s === 'review' || count([s]) > 0)
  // ⓘ 는 화면 안에서 처음 나오는 곳에만 (R2): 1위 불일치·같은 이름은 보이는 행 중 첫 행
  const firstClose = visible.find(isClose)?.id
  const grouped = rows.some((r) => r.part_no) // 부품번호가 있는 세션만 묶는다(없으면 평평한 표)
  const groups = grouped ? groupByPart(visible, rows) : [{ key: 'all', rows: visible }]
  const firstRole = visible.find((r) => r.input_role)?.id // 구분 ⓘ 는 첫 행에만
  const firstCombined = visible.find((r) => r.selected?.role === '합본')?.id
  const firstNoUnit = visible.find((r) => r.selected && r.selected.reference_unit == null)?.id
  const firstDup = visible.find((r) => r.candidates.find((c) => c.dataset_id === r.selected_id)?.duplicate_group)?.id

  return (
    <>
      <div className="head split">
        <div>
          <h1>결과 검토</h1>
          <p>자동 매칭 결과를 확인하고 행마다 데이터셋을 승인합니다.</p>
          {data && <p className="note">{data.filename} · {data.rows.length}행</p>}
        </div>
        <div className="actions">
          <div className="actions-row">
            <button type="button" className="btn pri" onClick={() => download(EXPORT_MOCK ? 'csv' : 'xlsx')} disabled={!data}>
              승인분 내보내기{EXPORT_MOCK ? ' (CSV)' : ''}
            </button>
            {!EXPORT_MOCK && <button type="button" className="btn" onClick={() => download('csv')} disabled={!data}>CSV로</button>}
            <Link className="btn" to="/upload">다시 업로드</Link>
          </div>
          {exportMsg && <p className="err" role="alert">{exportMsg}</p>}
        </div>
      </div>

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
          <div className="prog">
            <div>
              <b>{rows.length}행</b>
              {nonZero.map((s) => (
                <span key={s}>
                  {' · '}<i className={`dot pb-${BAR[s]}`} aria-hidden="true" />
                  {s === 'approved' ? terms.approved.label : STATUS[s][0]}{STATUS[s][2] && <Info term={STATUS[s][2]} />} {count([s])}
                </span>
              ))}
            </div>
            <div className="bar" aria-hidden="true">
              {nonZero.map((s) => <i key={s} className={`pb-${BAR[s]}`} style={{ width: `${(count([s]) / rows.length) * 100}%` }} title={`${STATUS[s][0]} ${count([s])}`} />)}
            </div>
          </div>

          <div className="toolbar">
            <div className="tabs" role="group" aria-label="보기">
              {TABS.map((t) => (
                <button key={t.key} type="button" className="tab" aria-pressed={t.key === tab.key} onClick={() => setParam({ tab: t.key === TABS[0].key ? '' : t.key })}>
                  {t.label}<span className="num">{count(t.states)}</span>
                </button>
              ))}
            </div>
            <form
              className="search-row sm"
              role="search"
              onSubmit={(e) => {
                e.preventDefault()
                setParam({ q: e.currentTarget.elements.q.value.trim() })
              }}
            >
              {/* key: 뒤로가기로 q가 바뀌면 입력칸도 맞춘다 */}
              <input name="q" className="inp" aria-label="품명 검색" placeholder="품명 검색" key={q} defaultValue={q} maxLength={100} />
              <button type="submit" className="btn">검색</button>
            </form>
          </div>

          {tab.key === 'review' && (selectedIds.length > 0 || bulk.report) && (
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
            <div className="state"><p>이 탭에 해당하는 행 없음.</p></div>
          ) : (
            <table className="tbl rows">
              <thead>
                <tr>
                  {tab.key === 'review' && <th><span className="visually-hidden">선택</span></th>}
                  <th>입력</th><th>현재 선택</th>
                  <th>{terms.confidence.label}<Info term="confidence" /></th><th>{terms.conversion.label}<Info term="conversion" /></th><th>상태</th>
                  <th><span className="visually-hidden">동작</span></th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <Fragment key={g.key}>
                {grouped && (
                  <tr className="grp">
                    <th colSpan={tab.key === 'review' ? 7 : 6} scope="colgroup">
                      {g.part_no ? <>부품번호 {g.part_no} · {g.title}</> : '부품번호 없음'}
                      {g.warn && <span className="grp-warn"> · 가공이 두 번 계산될 수 있음<Info term="combined" /></span>}
                    </th>
                  </tr>
                )}
                {g.rows.map((row) => {
                  const status = statusOf.get(row.id)
                  const [label, tone] = STATUS[status]
                  const current = currentText(row)
                  const hasSel = typeof current !== 'string'
                  const blocked = bulkBlock(row)
                  const attrs = attrLine(row.attrs)
                  const rowName = row.clean.name || row.raw.name
                  const qty = row.clean.quantity ?? row.raw.quantity
                  return (
                    <tr key={row.id} className={[String(row.id) === openId && 'sel', tab.key === 'review' && 'has-chk'].filter(Boolean).join(' ') || undefined}>
                      {tab.key === 'review' && (
                        <td className="c-chk">
                          <Reason when={blocked != null} text={`승인할 수 없는 상태: ${blocked}`}>
                            <input
                              type="checkbox"
                              aria-label={`${rowName} 선택`}
                              disabled={blocked != null || bulk.busy}
                              checked={selectedIds.includes(row.id)}
                              onChange={() => toggleSelect(row.id)}
                            />
                          </Reason>
                        </td>
                      )}
                      <td className="c-in">
                        <b>{rowName}</b>
                        <span className="sub">{[row.raw.spec, `${qty || '—'} ${row.clean.unit_display ?? row.raw.unit}`].filter(Boolean).join(' · ')}</span>
                        {row.input_role && <span className="sub">{terms.input_role.label} {row.input_role}{row.id === firstRole && <Info term="input_role" />}</span>}
                        {(attrs || row.synonym_hits.length > 0) && (
                          <span className="sub">{attrs}{row.synonym_hits.length > 0 && `${attrs ? ' · ' : ''}사전: ${row.synonym_hits.join(', ')}`}</span>
                        )}
                      </td>
                      <td className="c-cand">
                        {hasSel ? (
                          <>
                            <b>{current.sel.name}</b>
                            <span className="sub">{current.cand ? orgYearVersion(current.cand) : current.sel.category}</span>
                            {current.cand?.duplicate_group && (
                              <span className="sub">
                                {sameName(current.cand.duplicate_group.size)} 중 {current.cand === row.candidates[0] ? '최신' : '하나'}
                                {row.id === firstDup && <Info term="duplicate_group" />}
                              </span>
                            )}
                            {current.sel.role && (
                              <span className="sub">
                                {terms.dataset_role.label} {current.sel.role}
                                {row.id === firstRole && <Info term="dataset_role" />}
                                {current.sel.role === '합본' && row.id === firstCombined && <Info term="combined" />}
                              </span>
                            )}
                            {current.sel.reference_unit == null && (
                              <span className="sub">{terms.no_reference_unit.label}{row.id === firstNoUnit && <Info term="no_reference_unit" />}</span>
                            )}
                            {current.sel.manual && <span className="sub">직접 선택</span>}
                          </>
                        ) : current}
                      </td>
                      <td className="c-conf">
                        {hasSel && current.sel.confidence ? current.sel.confidence : '—'}
                        {current.cand?.reasons.length > 0 && <span className="sub">{current.cand.reasons.join(' · ')}</span>}
                        {isClose(row) && <span className="sub">{terms.rank_mismatch.label}{row.id === firstClose && <Info term="rank_mismatch" />}</span>}
                      </td>
                      <td className="nowrap">{conversionLabel(row)}{conversionHint(row) && <Info>{conversionHint(row)}</Info>}</td>
                      <td className="nowrap"><span className={`st ${tone}`}>● {label}</span></td>
                      <td className="nowrap">
                        <Link className={status === 'approved' ? 'text-btn' : 'btn sm'} data-open={row.id} to={`/results/${sessionId}/rows/${row.id}${search}`}>
                          {status === 'approved' ? '보기' : '후보 확인'}
                        </Link>
                      </td>
                    </tr>
                  )
                })}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {data && <Outlet context={{ sessionId, rows, visibleIds, update, explain, search }} />}

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
    </>
  )
}

export default ResultsPage
