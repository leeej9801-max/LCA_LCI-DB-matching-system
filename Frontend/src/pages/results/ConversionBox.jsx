import { useState } from 'react'
import terms from '@/terms'
import { conversionDone } from './format'

// conversion.missing 의 이름 → 입력란. 범위는 명세(A03)와 같다. 환산 계산은 서버(mock) 몫이고 화면은 값만 보낸다
const FIELDS = [
  { missing: '두께', id: 'thk', key: 'thickness_mm', label: '두께 (mm)', ok: (v) => v > 0 && v <= 1000, hint: '0 초과 1000 이하로 입력해 주세요' },
  { missing: '밀도', id: 'den', key: 'density_kg_m3', label: '밀도 (kg/m³)', ok: (v) => v > 0, hint: '0보다 크게 입력해 주세요' },
  { missing: '개당 중량', id: 'umass', key: 'unit_mass_kg', label: '개당 중량 (kg/개)', ok: (v) => v > 0 && v <= 1000, hint: '0 초과 1000 이하로 입력해 주세요' },
]

// 단위 변환 상자 (U7 2-3): 입력 → 기준 단위, 변환 없음/필요 안내. 응답의 conversion 을 그대로 보여 주고, missing 에 해당하는 입력란을 연다 (A03 overrides 만 전송).
// 승인 버튼은 여기에 두지 않는다(결정은 패널 맨 아래 한 줄)
const ConversionBox = ({ row, busy, error, onCheck }) => {
  const c = row.conversion
  const [values, setValues] = useState(() => Object.fromEntries(FIELDS.map((f) => [f.key, row.overrides[f.key] ?? ''])))
  const [problem, setProblem] = useState({})

  const needed = c?.status === 'needs_info' ? FIELDS.filter((f) => c.missing.includes(f.missing)) : []
  const rangeField = error?.code === 'OUT_OF_RANGE' ? error.meta?.field : null // 400: 해당 입력칸 옆에
  const input = `${row.clean.quantity ?? row.raw.quantity ?? '—'} ${row.clean.unit_display ?? row.raw.unit}`
  const ref = row.selected?.reference_unit
  const state = !c ? null
    : c.status === 'ok' ? [terms.conversion.states.ok, 'ok']
      : c.status === 'converted' ? [terms.conversion.states.converted, 'ok']
        : c.status === 'needs_info' ? [terms.conversion.input(c.missing), 'warn']
          : [terms.conversion.states.incompatible, 'warn']

  const submit = (e) => {
    e.preventDefault()
    const next = Object.fromEntries(needed.filter((f) => !(values[f.key] !== '' && f.ok(Number(values[f.key])))).map((f) => [f.key, f.hint]))
    setProblem(next)
    if (Object.keys(next).length) return
    onCheck(Object.fromEntries(needed.map((f) => [f.key, Number(values[f.key])])))
  }

  return (
    <section className="u7-box" id="conv" aria-label={terms.conversion.label}>
      <div className="box-h">{terms.conversion.label}{state && <span className={`conv-state ${state[1]}`}>{state[0]}</span>}</div>
      {!row.selected ? (
        <p className="sub">후보를 고르면 단위 변환 결과가 여기에 나옵니다.</p>
      ) : (
        <>
          <div className="conv-line">
            <span>{input}</span><span className="arrow" aria-hidden="true">→</span>
            <span>
              {conversionDone(row) && c.status === 'converted' ? `${c.value} ${c.unit}`
                : ref == null ? terms.no_reference_unit.label : `${terms.reference_flow.label} ${ref}`}
            </span>
          </div>
          {c?.message && <p className="sub">{c.message}{conversionDone(row) && c.method && c.method !== 'identity' ? ` · ${terms.conversion.methods[c.method] ?? c.method}` : ''}</p>}
          {c?.status === 'incompatible' && <p className="sub">이 행은 제외하거나 다른 후보를 고르세요.</p>}
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
                    <span id={`${f.id}-err`} className="err" role="alert">{problem[f.key] ?? (rangeField === f.key ? error.detail : '')}</span>
                  </div>
                ))}
              </div>
              <button type="submit" className="btn sm" disabled={busy}>입력값으로 변환</button>
            </form>
          )}
        </>
      )}
      {error && rangeField && !needed.some((f) => f.key === rangeField) && <p className="err" role="alert">{error.detail}</p>}
    </section>
  )
}

export default ConversionBox
