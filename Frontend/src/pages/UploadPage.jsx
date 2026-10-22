import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { isMock } from '@/api/client'
import { getJob } from '@/api/jobs'
import { createSession, getBomTemplate, getSampleCsv, previewUpload } from '@/api/sessions'
import DevInfo from '@/components/DevInfo'
import MockNotice from '@/components/MockNotice'
import Reason from '@/components/Reason'
import terms from '@/terms'
import { retryable, uploadErrorText } from './upload/errorText'

const SESSIONS_MOCK = isMock('/sessions') // mock 모드: 샘플이 미리 계산된 결과로 바로 열린다. 실제 모드: A08 → A01 → A21 폴링
const TEMPLATE_MOCK = isMock('/bom/template')
const OPTIONAL_COLS = ['구분', '부품번호'] // 선택 열(T13): 없어도 "확인 필요"로 세지 않고 접힌 영역에 둔다
const SAMPLE_NAME = '부품BOM_샘플.csv' // mock은 이 이름이면 미리 계산된 결과로 본다 (spec/08 §7)
// 처리 현황의 단계. "파일 읽기"는 작업(job)이 만들어졌다는 것 자체(A01 이 파일을 먼저 읽고 202 를 준다)라 API 단계에 없다. 나머지는 A21 stages 이름을 화면 말로
const STAGE_LABEL = { 정규화: '품명 정리' }
const API_STAGES = ['정규화', '후보 검색', '판정·환산'] // job 응답을 받기 전의 자리표시(이름은 서버 STAGES 와 같다)
// 읽는 열 (Backend/app/bom/mapping.py FIELDS 와 같다: 품명·단위·수량 필수, 규격·부품번호·구분 선택). 화면 이름은 FTA 양식 표기
const READ_COLS = [['품명(국문)', true], ['단위', true], ['소요량', true], ['규격', false], ['품번', false], ['구분(소재/공정)', false]]

const saveBlob = (blob, name) => {
  const url = URL.createObjectURL(blob)
  Object.assign(document.createElement('a'), { href: url, download: name }).click()
  URL.revokeObjectURL(url)
}

// 처리 현황 단계: [{ label, state: 'done'|'now'|'wait', sub }]
const railSteps = (run, rowsTotal) => {
  const job = run?.job
  if (!run) return ['파일 읽기', ...API_STAGES.map((n) => STAGE_LABEL[n] ?? n)].map((label) => ({ label, state: 'wait', sub: '대기' })) // 아직 올린 파일이 없다
  const stages = job?.stages ?? API_STAGES.map((name) => ({ name, state: 'queued', done: 0, total: 0 }))
  return [
    { label: '파일 읽기', state: 'done', sub: rowsTotal != null ? `${rowsTotal}행` : '' },
    ...stages.map((s) => ({
      label: STAGE_LABEL[s.name] ?? s.name,
      state: s.state === 'succeeded' ? 'done' : s.state === 'running' ? 'now' : 'wait',
      sub: s.state === 'succeeded' ? (s.total > 0 ? `${s.total}행` : '') : s.state === 'running' ? (s.total > 0 ? `${s.done} / ${s.total}` : '진행 중') : '대기',
    })),
  ]
}

const Doc = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></svg>
)
const Down = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>
)

// S1 BOM 업로드 (FR-301). 파일 고르기 → 미리보기(컬럼 매핑) → 진행 → 결과(S2)
const UploadPage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null) // A20 응답
  const [picks, setPicks] = useState({}) // 사람이 고른 대응 { 필드: 파일 컬럼명 | '' }
  const [error, setError] = useState(null) // { detail, retry? } 파일 영역 바로 아래 한 줄
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState(() => (searchParams.get('job') ? { jobId: searchParams.get('job') } : null)) // { jobId, job? }. ?job= 은 결과 화면(409 JOB_NOT_FINISHED)에서 돌아온 경우
  const [over, setOver] = useState(false)

  const reset = () => { setPreview(null); setPicks({}); setError(null); setRun(null) }

  const pick = async (f) => {
    reset()
    setFile(f)
    setBusy(true)
    try {
      setPreview(await previewUpload(f))
    } catch (e) {
      setError({ detail: uploadErrorText(e) })
    } finally {
      setBusy(false)
    }
  }

  // 사람이 고른 것만 mapping 으로 보낸다. 자동 인식은 서버가 다시 한다
  const picksToMapping = () => {
    const entries = Object.entries(picks).filter(([, v]) => v)
    return entries.length ? Object.fromEntries(entries) : undefined
  }

  const start = async (f, mapping) => {
    setError(null)
    setBusy(true)
    try {
      const { job_id: id } = await createSession(f, mapping)
      setRun({ jobId: id })
    } catch (e) {
      setError({ detail: uploadErrorText(e), retry: retryable(e) ? () => start(f, mapping) : undefined })
    } finally {
      setBusy(false)
    }
  }

  const trySample = async () => {
    reset()
    setBusy(true)
    try {
      const blob = await getSampleCsv()
      const sample = new File([blob], SAMPLE_NAME, { type: 'text/csv' })
      setFile(sample)
      await start(sample)
    } catch (e) {
      setError({ detail: uploadErrorText(e), retry: retryable(e) ? trySample : undefined })
      setBusy(false)
    }
  }

  // 소개 화면의 "샘플로 해 보기"가 state 로 넘겨 주면 같은 trySample 로 시작한다(새로고침 때 다시 시작하지 않게 state 를 지운다)
  const sampleAsked = useRef(false)
  useEffect(() => {
    if (!location.state?.sample || sampleAsked.current) return
    sampleAsked.current = true
    navigate(location.pathname, { replace: true, state: null })
    trySample()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 도착했을 때 한 번만
  }, [])

  const download = async (get, name) => {
    setError(null)
    try {
      saveBlob(await get(), name)
    } catch (e) {
      setError({ detail: uploadErrorText(e) })
    }
  }

  // 진행: A21 폴링. 실행 중 1초, 10초가 지나면 3초 간격 (spec/08 §2)
  const jobId = run?.jobId
  useEffect(() => {
    if (!jobId) return
    let ignore = false
    let timer
    const t0 = Date.now()
    const fail = (detail, again = true) => {
      setRun(null)
      setError({ detail, retry: file && again ? () => start(file, picksToMapping()) : undefined }) // 파일을 모르는 채 돌아온 진행 화면(?job=)은 다시 올려야 한다
    }
    const tick = async () => {
      try {
        const job = await getJob(jobId)
        if (ignore) return
        if (job.state === 'succeeded') navigate(`/results/${job.result.session_id}`)
        else if (job.state === 'failed') fail(job.error?.detail ?? '매칭에 실패했습니다.')  // detail 은 서버 문구(예: Ollama 에 접속하지 못했습니다)
        else {
          setRun({ jobId, job })
          timer = setTimeout(tick, Date.now() - t0 < 10000 ? 1000 : 3000)
        }
      } catch (e) {
        if (!ignore) fail(uploadErrorText(e), retryable(e))
      }
    }
    tick()
    return () => { ignore = true; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- jobId가 바뀔 때만 새로 시작한다
  }, [jobId])

  // 컬럼 대응: 자동 인식(source) 위에 사람이 고른 것을 얹는다
  const mapping = preview?.column_mapping ?? []
  const sourceOf = (m) => (m.field in picks ? picks[m.field] || null : m.source)
  const mapped = mapping.filter(sourceOf)
  const missingRequired = mapping.filter((m) => m.required && !sourceOf(m))
  const optionalCols = mapping.filter((m) => OPTIONAL_COLS.includes(m.field))
  const missingOptional = mapping.filter((m) => !m.required && !sourceOf(m) && !OPTIONAL_COLS.includes(m.field)) // 선택 열은 세지 않는다
  const pickable = mapping.filter((m) => m.method === 'missing' && !OPTIONAL_COLS.includes(m.field)) // 자동으로 못 찾은 필드만 드롭다운
  const optionalPickable = optionalCols.filter((m) => m.method === 'missing')
  const optionalFound = optionalCols.filter(sourceOf)
  const fieldOf = (col) => mapping.find((m) => sourceOf(m) === col)?.field
  const working = busy || !!run

  const job = run?.job
  const steps = railSteps(run, preview?.rows_total ?? null)
  const firstOpen = steps.findIndex((s) => s.state !== 'done')
  const filled = !run ? 0 : (firstOpen === -1 ? steps.length - 1 : firstOpen) / (steps.length - 1)
  const running = job?.stages?.find((s) => s.state === 'running')
  const percent = running?.total ? Math.round((running.done / running.total) * 100) : job?.state === 'succeeded' ? 100 : 0
  const phase = !run ? null : job?.state === 'queued' ? '대기 중' : running ? `${STAGE_LABEL[running.name] ?? running.name} 중` : job ? '마무리 중' : '시작하는 중'

  return (
    <div className="u7">
      <div className="u7-title">
        <h1>BOM 업로드</h1>
        <p>부품 BOM을 올리면 국가 LCI DB에서 맞는 데이터셋 후보를 찾아 줍니다.</p>
      </div>

      <ol className="u7-steps" aria-label="사용 순서">
        <li className="now" aria-current="step"><span className="n">1</span>파일 올리기</li>
        <li className="bar" aria-hidden="true" />
        <li><span className="n">2</span>후보 확인·승인</li>
        <li className="bar" aria-hidden="true" />
        <li><span className="n">3</span>내보내기</li>
      </ol>

      <div className="u7-cols">
        <section className="u7-card u7-main" aria-label="파일 올리기">
          <div
            className={over ? 'u7-drop over' : 'u7-drop'}
            onDragOver={(e) => { e.preventDefault(); setOver(true) }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setOver(false)
              if (!working && e.dataTransfer.files[0]) pick(e.dataTransfer.files[0])
            }}
          >
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
            <p className="big">BOM 파일을 여기에 끌어 놓으세요</p>
            <p className="or">또는 <button type="button" className="btn" disabled={working} onClick={() => inputRef.current.click()}>파일 선택</button></p>
            <input
              ref={inputRef} type="file" className="visually-hidden" accept=".csv,.xlsx,.xls" aria-label="BOM 파일" tabIndex={-1}
              onChange={(e) => { if (e.target.files[0]) pick(e.target.files[0]); e.target.value = '' }}
            />
            <p className="limit">xlsx · xls · csv · 최대 5MB · 2,000행</p>
            {file && <p className="limit">선택한 파일: {file.name}</p>}
          </div>
          <h2 className="cols-h">읽는 열</h2>
          <div className="cols">
            {READ_COLS.map(([name, required]) => (
              <span key={name} className="col-chip">{name}<span className={required ? 'req' : 'opt'}>{required ? '필수' : '선택'}</span></span>
            ))}
          </div>
          <p className="hint">FTA 원산지 자재명세서 양식을 그대로 올려도 됩니다. 구분을 비우면 품명으로 공정 여부를 추정합니다.</p>
          <p className="hint">올린 BOM은 서버에 저장되어 이 화면에서 결과를 볼 때 쓰입니다. <strong>회사 기밀 BOM은 올리지 마세요.</strong> 저장 기간: 24시간.</p>
        </section>

        <div className="u7-side">
          <section className="u7-card" aria-label="양식 내려받기">
            <h2>양식 내려받기</h2>
            <Reason when={TEMPLATE_MOCK} text="곧 제공됩니다">
              <button type="button" className="dl-row" disabled={TEMPLATE_MOCK || working} onClick={() => download(() => getBomTemplate('blank'), 'fta-bom-template.xlsx')}>
                <span className="ico"><Doc /></span>
                <span className="txt"><b>빈 양식</b><span>FTA 자재명세서 · xlsx</span></span>
                <span className="dl"><Down /></span>
              </button>
            </Reason>
            <Reason when={TEMPLATE_MOCK} text="곧 제공됩니다">
              <button type="button" className="dl-row" disabled={TEMPLATE_MOCK || working} onClick={() => download(() => getBomTemplate('sample'), 'fta-bom-sample.xlsx')}>
                <span className="ico"><Doc /></span>
                <span className="txt"><b>예시가 채워진 샘플</b><span>19행 · xlsx</span></span>
                <span className="dl"><Down /></span>
              </button>
            </Reason>
            <div className="try">
              <span className="txt"><b>바로 해 보기</b><span>샘플 BOM으로 결과 화면을 엽니다</span></span>
              <button type="button" className="btn" disabled={working} onClick={trySample}>샘플로 시작</button>
            </div>
          </section>

          <section className="u7-card" aria-label="처리 현황" aria-live="polite">
            <div className="prog-h">
              <h2>처리 현황</h2>
              {file && <span className="meta ell">{file.name}{preview ? ` · ${preview.rows_total}행` : ''}</span>}
            </div>
            {run && <MockNotice path="/jobs" />}
            <ol className="rail" style={{ '--filled': filled }}>
              {steps.map((s, i) => (
                <li key={i} className={s.state}>
                  <span className="dot" aria-hidden="true">
                    {s.state === 'done' && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="3"><path d="M5 12.5 10 17l9-10" /></svg>}
                    {s.state === 'now' && <i />}
                  </span>
                  <span className="name">{s.label}</span>
                  <span className="cnt">{s.sub}</span>
                </li>
              ))}
            </ol>
            {run ? (
              <>
                <div className="prog-l"><span>{phase}</span>{running && <span>{percent}%</span>}</div>
                <div className="prog-t" role="progressbar" aria-label="처리 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div>
                <p className="hint">끝나면 결과 화면으로 넘어갑니다.</p>
              </>
            ) : (
              <p className="hint">파일을 올리면 여기에 진행 상황이 나옵니다.</p>
            )}
          </section>
        </div>
      </div>

      {error && (
        <p className="err" role="alert">
          {error.detail}
          {error.retry && <> <button type="button" className="text-btn" onClick={error.retry}>다시 시도</button></>}
        </p>
      )}

      {preview && !run && (
        <section className="u7-card u7-map" aria-label="컬럼 대응">
          <MockNotice path="/sessions" />
          <p className="summary-line">
            <b>
              {mapped.length}개 컬럼 인식
              {missingRequired.length > 0
                ? ` · ${missingRequired.map((m) => m.field).join('·')} 컬럼을 찾지 못했습니다`
                : missingOptional.length > 0 && ` · ${missingOptional.length}개 열을 골라 주세요`}
            </b>
            <span className="note">{preview.rows_total}행 · 앞 5행 미리보기 · 회사마다 열 이름이 달라 어느 열이 품명·규격·단위·수량인지 맞춰 둡니다</span>
            {(preview.rows_skipped?.example > 0 || preview.rows_skipped?.empty_name > 0) && (
              <span className="note">
                {' · '}양식 예시 {preview.rows_skipped.example}행, 품명이 빈 {preview.rows_skipped.empty_name}행은 제외했습니다
              </span>
            )}
          </p>

          <div className="optcols">
            <p className="note">
              {optionalFound.length > 0
                ? <>선택 열 인식: {optionalFound.map((m) => `${m.field === '구분' ? terms.input_role.label : m.field}=${sourceOf(m)}`).join(', ')}</>
                : `선택 열(${terms.input_role.label} "구분"·부품번호)이 없습니다. 없으면 소재·공정을 가리지 않고 찾습니다.`}
            </p>
            {optionalPickable.length > 0 && (
              <details>
                <summary>선택 열({terms.input_role.label}·부품번호) 직접 고르기</summary>
                <div className="row-inputs">
                  {optionalPickable.map((m) => (
                    <div className="field" key={m.field}>
                      <label className="lb" htmlFor={`map-${m.field}`}>{m.field === '구분' ? `${terms.input_role.label}(구분)` : m.field} (선택)</label>
                      <select
                        id={`map-${m.field}`} className="inp" value={picks[m.field] ?? ''}
                        onChange={(e) => setPicks({ ...picks, [m.field]: e.target.value })}
                      >
                        <option value="">컬럼 고르기</option>
                        {preview.file_columns
                          .filter((c) => c === picks[m.field] || !mapping.some((o) => sourceOf(o) === c))
                          .map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>

          {pickable.length > 0 && (
            <div className="row-inputs">
              {pickable.map((m) => (
                <div className="field" key={m.field}>
                  <label className="lb" htmlFor={`map-${m.field}`}>{m.field}{m.required ? ' (필수)' : ' (선택)'}</label>
                  <select
                    id={`map-${m.field}`} className="inp" value={picks[m.field] ?? ''}
                    onChange={(e) => setPicks({ ...picks, [m.field]: e.target.value })}
                  >
                    <option value="">컬럼 고르기</option>
                    {preview.file_columns
                      .filter((c) => c === picks[m.field] || !mapping.some((o) => sourceOf(o) === c))
                      .map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              ))}
            </div>
          )}

          <div className="pv-scroll">
            <table className="pv">
              <thead>
                <tr>
                  {preview.file_columns.map((c, i) => <th key={i} className={fieldOf(c) ? undefined : 'dim'}><span className="pv-field">{fieldOf(c) ?? '—'}</span>{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {preview.preview_rows.map((row, r) => (
                  <tr key={r}>{row.map((v, i) => <td key={i} className={fieldOf(preview.file_columns[i]) ? undefined : 'dim'}>{v}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <Reason when={missingRequired.length > 0} text={`${missingRequired.map((m) => m.field).join('·')} 컬럼을 위에서 골라야 실행할 수 있습니다`}>
              <button type="button" className="btn pri" disabled={working || missingRequired.length > 0} onClick={() => start(file, picksToMapping())}>매칭 실행</button>
            </Reason>
          </div>
        </section>
      )}

      <DevInfo>
        <p className="note">S1 · FR-301</p>
        {SESSIONS_MOCK && <p className="note">mock: 예시 결과로 이동합니다 · <Link to="/results/7f3a9c21d0b4">예시 세션 열기</Link></p>}
        <table className="api">
          <tbody>
            <tr><td className="i">A20<b>+</b></td><td className="m">POST</td><td>{'/api/sessions/preview'}</td></tr>
            <tr><td className="i">A01</td><td className="m">POST</td><td>{'/api/sessions'}</td></tr>
            <tr><td className="i">A21<b>+</b></td><td className="m">GET</td><td>{'/api/jobs/{job_id}'}</td></tr>
            <tr><td className="i">A08</td><td className="m">GET</td><td>{'/api/sample.csv'}</td></tr>
            <tr><td className="i">A08b<b>+</b></td><td className="m">GET</td><td>{'/api/template.xlsx'}</td></tr>
          </tbody>
        </table>
      </DevInfo>
    </div>
  )
}

export default UploadPage
