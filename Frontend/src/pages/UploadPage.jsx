import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { isMock } from '@/api/client'
import { getJob } from '@/api/jobs'
import { createSession, getSampleCsv, getTemplate, previewUpload } from '@/api/sessions'
import DevInfo from '@/components/DevInfo'
import Info from '@/components/Info'
import MockNotice from '@/components/MockNotice'
import Reason from '@/components/Reason'
import terms from '@/terms'
import { retryable, uploadErrorText } from './upload/errorText'

const SESSIONS_MOCK = isMock('/sessions') // mock 모드: 샘플이 미리 계산된 결과로 바로 열린다. 실제 모드: A08 → A01 → A21 폴링
const TEMPLATE_MOCK = isMock('/template.xlsx')
const OPTIONAL_COLS = ['구분', '부품번호'] // 선택 열(T13): 없어도 "확인 필요"로 세지 않고 접힌 영역에 둔다
const SAMPLE_NAME = '부품BOM_샘플.csv' // mock은 이 이름이면 미리 계산된 결과로 본다 (spec/08 §7)
const STAGE_STATE = { queued: '대기', running: '진행 중', succeeded: '완료' }
// 드롭 영역의 양식 예시 (샘플 BOM 의 행). [품명, 규격, 단위, 수량]
const TEMPLATE_ROWS = [['SPCC 냉연강판', 't1.2 x 120 x 340', 'kg', '2.4'], ['볼트 M6x20', '', 'EA', '20'], ['알루미늄 판재 A5052', 't2', 'm2', '0.8']]

const saveBlob = (blob, name) => {
  const url = URL.createObjectURL(blob)
  Object.assign(document.createElement('a'), { href: url, download: name }).click()
  URL.revokeObjectURL(url)
}

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

  return (
    <>
      <div className="head">
        <h1>BOM 업로드</h1>
        <p>자동차 부품 BOM을 올리면 국가 LCI DB의 {terms.lci_dataset.label}<Info term="lci_dataset" /> 후보를 찾아 줍니다.</p>
        <ol className="upload-steps" aria-label="사용 순서">
          <li>① BOM 올리기</li><li>② 후보 확인·승인</li><li>③ 승인한 행 내보내기</li>
        </ol>
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
          <p className="note">CSV·XLSX, 5MB · 2,000행까지 · 첫 행은 열 이름. 아래처럼 4열이면 됩니다</p>
          <table className="tpl" aria-label="양식 예시">
            <thead>
              <tr>
                <th>품명 <span className="note">필수</span></th><th>규격 <span className="note">선택</span></th>
                <th>단위 <span className="note">필수</span></th><th>수량 <span className="note">필수</span></th>
              </tr>
            </thead>
            <tbody>{TEMPLATE_ROWS.map((r) => <tr key={r[0]}>{r.map((v, i) => <td key={i}>{v}</td>)}</tr>)}</tbody>
          </table>
          {file && <p className="note">선택한 파일: {file.name}</p>}
        </div>
        <div className="side-actions">
          <button type="button" className="btn" disabled={working} onClick={trySample}>샘플로 해 보기</button>
          <p className="note">샘플 BOM으로 바로 매칭해 결과 화면을 엽니다</p>
          <button type="button" className="text-btn" disabled={working} onClick={() => download(getSampleCsv, SAMPLE_NAME)}>예시 파일 내려받기</button>
          <p className="note">값이 채워진 샘플 BOM(CSV)을 받아 열어 봅니다</p>
          <Reason when={TEMPLATE_MOCK} text="곧 제공됩니다">
            <button type="button" className="text-btn" disabled={TEMPLATE_MOCK || working} onClick={() => download(getTemplate, 'BOM_양식.xlsx')}>빈 양식 내려받기</button>
          </Reason>
          <p className="note">열 이름만 있는 엑셀 양식에 내 BOM을 채웁니다</p>
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
          <MockNotice path="/sessions" />
          <p className="summary-line">
            <b>
              {mapped.length}개 컬럼 인식
              {missingRequired.length > 0
                ? ` · ${missingRequired.map((m) => m.field).join('·')} 컬럼을 찾지 못했습니다`
                : missingOptional.length > 0 && ` · ${missingOptional.length}개 확인 필요`}
            </b>
            <Info>회사마다 BOM 열 이름이 달라서, 어느 열이 품명·규격·단위·수량인지 맞춰 둡니다.</Info>
            <span className="note">{preview.rows_total}행 · 앞 5행 미리보기</span>
          </p>

          <div className="optcols">
            <p className="note">
              {optionalFound.length > 0
                ? <>선택 열 인식: {optionalFound.map((m) => `${m.field}=${sourceOf(m)}`).join(', ')}</>
                : '선택 열(구분·부품번호)이 없습니다. 없으면 소재·공정을 가리지 않고 찾습니다.'}
              <Info term="input_role" />
            </p>
            {optionalPickable.length > 0 && (
              <details>
                <summary>선택 열(구분·부품번호) 직접 고르기</summary>
                <div className="row-inputs">
                  {optionalPickable.map((m) => (
                    <div className="field" key={m.field}>
                      <label className="lb" htmlFor={`map-${m.field}`}>{m.field} (선택)</label>
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
              <button type="button" className="btn pri lg" disabled={working || missingRequired.length > 0} onClick={() => start(file, picksToMapping())}>매칭 실행</button>
            </Reason>
          </div>
        </section>
      )}

      {run && (
        <section className="sec" aria-label="매칭 진행" aria-live="polite">
          <MockNotice path="/jobs" />
          <p className="summary-line"><b>{run.job?.state === 'queued' ? '대기 중' : '매칭 중'}</b></p>
          <ul className="stages">
            {(run.job?.stages ?? []).map((s) => (
              <li key={s.name}><span>{s.name}</span><span className="num">{s.done}/{s.total}</span><span className="note">{STAGE_STATE[s.state]}</span></li>
            ))}
          </ul>
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
    </>
  )
}

export default UploadPage
