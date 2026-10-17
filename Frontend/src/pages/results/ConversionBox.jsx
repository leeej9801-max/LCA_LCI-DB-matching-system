import { useState } from 'react'
import { conversionDone } from './format'

// conversion.missing 의 이름 → 입력란. 범위는 명세(A03)와 같다. 환산 계산은 서버(mock) 몫이고 화면은 값만 보낸다
const FIELDS = [
  { missing: '두께', id: 'thk', key: 'thickness_mm', label: '두께 (mm)', ok: (v) => v > 0 && v <= 1000, hint: '0 초과 1000 이하로 입력해 주세요' },
  { missing: '밀도', id: 'den', key: 'density_kg_m3', label: '밀도 (kg/m³)', ok: (v) => v > 0, hint: '0보다 크게 입력해 주세요' },
  { missing: '개당 중량', id: 'umass', key: 'unit_mass_kg', label: '개당 중량 (kg/개)', ok: (v) => v > 0 && v <= 1000, hint: '0 초과 1000 이하로 입력해 주세요' },
]

// 환산 상태: 응답의 conversion 을 그대로 보여 주고, missing 에 해당하는 입력란을 연다 (A03 overrides 만 전송)
const ConversionBox = ({ row, busy, error, onCheck, onApprove }) => {
  const c = row.conversion
  const [values, setValues] = useState(() => Object.fromEntries(FIELDS.map((f) => [f.key, row.overrides[f.key] ?? ''])))
  const [problem, setProblem] = useState({})

  const needed = c?.status === 'needs_info' ? FIELDS.filter((f) => c.missing.includes(f.missing)) : []
  const approved = row.review.status === 'approved'

  const submit = (e) => {
    e.preventDefault()
    const next = Object.fromEntries(needed.filter((f) => !(values[f.key] !== '' && f.ok(Number(values[f.key])))).map((f) => [f.key, f.hint]))
    setProblem(next)
    if (Object.keys(next).length) return
    onCheck(Object.fromEntries(needed.map((f) => [f.key, Number(values[f.key])])))
  }

  return (
    <section className="sec" id="conv">
      <h3>환산 상태</h3>
      {row.selected && <p className="note">선택: {row.selected.name}{row.selected.manual && ' · 직접 선택'}</p>}
      {!c ? (
        <p className="note">후보를 선택하면 환산 결과가 표시됩니다.</p>
      ) : (
        <>
          <p><b>{c.message}</b></p>
          {conversionDone(row) && <p>{c.value} {c.unit}{c.method && <span className="note"> · {c.method}</span>}</p>}
          {c.status === 'incompatible' && <p>이 행은 제외하거나 다른 후보를 고르세요.</p>}
          {needed.length > 0 && (
            <form className="conv-form" onSubmit={submit} noValidate>
              <div className="row-inputs">
                {needed.map((f) => (
                  <div className="field" key={f.key}>
                    <label className="lb" htmlFor={f.id}>{f.label}</label>
                    <input
                      id={f.id} className="inp" type="number" inputMode="decimal" step="any"
                      value={values[f.key]}
                      onChange={(e) => {
                        setValues({ ...values, [f.key]: e.target.value })
                        setProblem({ ...problem, [f.key]: undefined })
                      }}
                      aria-invalid={!!problem[f.key]} aria-describedby={`${f.id}-err`}
                    />
                    <span id={`${f.id}-err`} className="err" role="alert">{problem[f.key]}</span>
                  </div>
                ))}
              </div>
              <button type="submit" className="btn sm" disabled={busy}>환산 확인</button>
            </form>
          )}
        </>
      )}
      {error && <p className="err" role="alert">{error}</p>}
      {row.selected && (
        <div>
          <button type="button" className="btn pri sm" disabled={busy || approved || !conversionDone(row)} onClick={onApprove}>
            {approved ? '승인됨' : '현재 선택 승인'}
          </button>
        </div>
      )}
    </section>
  )
}

export default ConversionBox
