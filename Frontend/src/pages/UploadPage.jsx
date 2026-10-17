import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { getJob } from '@/api/jobs'
import { createSession, getSampleCsv, getTemplate, previewUpload } from '@/api/sessions'

const MOCK = import.meta.env.VITE_API_MOCK === '1'
const SAMPLE_NAME = '부품BOM_샘플.csv' // mock은 이 이름이면 미리 계산된 결과로 본다 (spec/08 §7)
const STAGE_STATE = { queued: '대기', running: '진행 중', succeeded: '완료' }

const saveBlob = (blob, name) => {
  const url = URL.createObjectURL(blob)
  Object.assign(document.createElement('a'), { href: url, download: name }).click()
  URL.revokeObjectURL(url)
}

// S1 BOM 업로드 (FR-301). 파일 고르기 → 미리보기(컬럼 매핑) → 진행 → 결과(S2)
const UploadPage = () => {
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null) // A20 응답
  const [picks, setPicks] = useState({}) // 사람이 고른 대응 { 필드: 파일 컬럼명 | '' }
  const [error, setError] = useState(null) // { detail, retry? } 파일 영역 바로 아래 한 줄
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState(null) // { jobId, job? }
  const [over, setOver] = useState(false)

  const reset = () => { setPreview(null); setPicks({}); setError(null); setRun(null) }

  const pick = async (f) => {
    reset()
    setFile(f)
    setBusy(true)
    try {
      setPreview(await previewUpload(f))
    } catch (e) {
      setError({ detail: e.detail })
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
      setError({ detail: e.detail, retry: e.status === 429 ? () => start(f, mapping) : undefined })
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
      setError({ detail: e.detail })
      setBusy(false)
    }
  }

  const download = async (get, name) => {
    setError(null)
    try {
      saveBlob(await get(), name)
    } catch (e) {
      setError({ detail: e.detail })
    }
  }

  // 진행: A21 폴링. 실행 중 1초, 10초가 지나면 3초 간격 (spec/08 §2)
  const jobId = run?.jobId
  useEffect(() => {
    if (!jobId) return
    let ignore = false
    let timer
    const t0 = Date.now()
    const fail = (detail) => {
      setRun(null)
      setError({ detail, retry: () => start(file, picksToMapping()) })
    }
    const tick = async () => {
      try {
        const job = await getJob(jobId)
        if (ignore) return
        if (job.state === 'succeeded') navigate(`/results/${job.result.session_id}`)
        else if (job.state === 'failed') fail(job.error?.detail ?? '매칭에 실패했습니다.')
        else {
          setRun({ jobId, job })
          timer = setTimeout(tick, Date.now() - t0 < 10000 ? 1000 : 3000)
        }
      } catch (e) {
        if (!ignore) fail(e.detail)
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
  const missingOptional = mapping.filter((m) => !m.required && !sourceOf(m))
  const pickable = mapping.filter((m) => m.method === 'missing') // 자동으로 못 찾은 필드만 드롭다운
  const fieldOf = (col) => mapping.find((m) => sourceOf(m) === col)?.field
  const working = busy || !!run

  return (
    <>
      <div className="head">
        <h1>BOM 업로드</h1>
        <p>자동차 부품 BOM을 올리면 국가 LCI DB 데이터셋 후보를 찾아 줍니다.</p>
      </div>

      <div className="upload">
        <div
          className={over ? 'drop over' : 'drop'}
          onDragOver={(e) => { e.preventDefault(); setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            if (!working && e.dataTransfer.files[0]) pick(e.dataTransfer.files[0])
          }}
        >
          <p>BOM 파일을 여기에 끌어 놓거나</p>
          <button type="button" className="btn" disabled={working} onClick={() => inputRef.current.click()}>파일 선택</button>
          <input
            ref={inputRef} type="file" className="visually-hidden" accept=".csv,.xlsx" aria-label="BOM 파일" tabIndex={-1}
            onChange={(e) => { if (e.target.files[0]) pick(e.target.files[0]); e.target.value = '' }}
          />
          <p className="note">CSV·XLSX, 5MB · 2,000행까지</p>
          {file && <p className="note">선택한 파일: {file.name}</p>}
        </div>
        <div className="side-actions">
          <button type="button" className="btn" disabled={working} onClick={trySample}>샘플로 해 보기</button>
          <button type="button" className="text-btn" disabled={working} onClick={() => download(getSampleCsv, SAMPLE_NAME)}>샘플 BOM 내려받기</button>
          <button
            type="button" className="text-btn" disabled={MOCK || working}
            title={MOCK ? '양식 파일은 서버 연결 후 내려받을 수 있습니다' : undefined}
            onClick={() => download(getTemplate, 'BOM_양식.xlsx')}
          >양식 내려받기</button>
        </div>
      </div>

      {error && (
        <p className="err" role="alert">
          {error.detail}
          {error.retry && <> <button type="button" className="text-btn" onClick={error.retry}>다시 시도</button></>}
        </p>
      )}

      {preview && !run && (
        <section className="sec" aria-label="컬럼 대응">
          <p className="summary-line">
            <b>
              {mapped.length}개 컬럼 인식
              {missingRequired.length > 0
                ? ` · ${missingRequired.map((m) => m.field).join('·')} 컬럼을 찾지 못했습니다`
                : missingOptional.length > 0 && ` · ${missingOptional.length}개 확인 필요`}
            </b>
            <button type="button" className="hint" title="회사마다 BOM 열 이름이 달라서, 어느 열이 품명·규격·단위·수량인지 맞춰 둡니다." aria-label="컬럼 대응이란: 회사마다 BOM 열 이름이 달라서, 어느 열이 품명·규격·단위·수량인지 맞춰 둡니다.">?</button>
            <span className="note">{preview.rows_total}행 · 앞 5행 미리보기</span>
          </p>

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
            <button type="button" className="btn pri lg" disabled={working || missingRequired.length > 0} onClick={() => start(file, picksToMapping())}>매칭 실행</button>
          </div>
        </section>
      )}

      {run && (
        <section className="sec" aria-label="매칭 진행" aria-live="polite">
          <p className="summary-line"><b>{run.job?.state === 'queued' ? '대기 중' : '매칭 중'}</b></p>
          <ul className="stages">
            {(run.job?.stages ?? []).map((s) => (
              <li key={s.name}><span>{s.name}</span><span className="num">{s.done}/{s.total}</span><span className="note">{STAGE_STATE[s.state]}</span></li>
            ))}
          </ul>
        </section>
      )}

      <details className="devinfo">
        <summary>개발 정보</summary>
        <p className="note">S1 · FR-301</p>
        {MOCK && <p className="note">mock: 예시 결과로 이동합니다 · <Link to="/results/7f3a9c21d0b4">예시 세션 열기</Link></p>}
        <table className="api">
          <tbody>
            <tr><td className="i">A20<b>+</b></td><td className="m">POST</td><td>{'/api/sessions/preview'}</td></tr>
            <tr><td className="i">A01</td><td className="m">POST</td><td>{'/api/sessions'}</td></tr>
            <tr><td className="i">A21<b>+</b></td><td className="m">GET</td><td>{'/api/jobs/{job_id}'}</td></tr>
            <tr><td className="i">A08</td><td className="m">GET</td><td>{'/api/sample.csv'}</td></tr>
            <tr><td className="i">A08b<b>+</b></td><td className="m">GET</td><td>{'/api/template.xlsx'}</td></tr>
          </tbody>
        </table>
      </details>
    </>
  )
}

export default UploadPage
