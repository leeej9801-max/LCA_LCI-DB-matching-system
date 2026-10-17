import sample from './data/session.mock.json'
import pool from './data/datasets.mock-pool.json'

// 메모리 상태: 새로고침하면 초기화된다 (세션은 예시 하나)
let session = structuredClone(sample)

const notFound = () => [404, { detail: '세션을 찾을 수 없습니다. 파일을 다시 업로드해 주세요.', code: 'SESSION_NOT_FOUND' }]
const rowNotFound = () => [404, { detail: '행을 찾을 수 없습니다.', code: 'ROW_NOT_FOUND' }]

const summarize = (rows) => {
  const n = (f) => rows.filter(f).length
  return {
    total: rows.length,
    target: n((r) => r.target.status === '대상'),
    exclude: n((r) => r.target.status === '제외'),
    needs_review: n((r) => r.review.status === 'pending'),
    with_issues: n((r) => r.issues.length > 0),
    needs_info: n((r) => r.conversion?.status === 'needs_info'),
    high_confidence: n((r) => r.candidates[0]?.confidence === '높음'),
    review: Object.fromEntries(['pending', 'approved', 'rejected', 'excluded'].map((k) => [k, n((r) => r.review.status === k)])),
    match: Object.fromEntries(['candidate', 'vetoed', 'no_answer'].map((k) => [k, n((r) => r.match_state === k)])),
  }
}

const AREA = ['m2', 'm²', '㎡']
const VOLUME = ['m3', 'm³', '㎥']

// shortcut: 같은 단위 · 개수(EA·개, 개당 중량) · 면적·부피(두께·밀도) · 그 밖은 불가. 그 밖의 단위 환산(g↔kg 등)은 백엔드에서
const convert = (row, ref) => {
  const { unit, unit_display, quantity } = row.clean
  const { thickness_mm: t, density_kg_m3: d, unit_mass_kg: m } = row.overrides
  const fail = (status, message, missing = []) => ({ status, value: null, unit: ref, message, missing, method: null })
  if (quantity == null) return fail('invalid', '수량이 없습니다')
  if (unit === ref) return { status: 'ok', value: quantity, unit, message: '기준흐름 단위와 같음', missing: [], method: 'identity' }
  if (unit === 'EA' || unit === '개') {
    if (m == null) return fail('needs_info', '개당 중량이 필요합니다', ['개당 중량'])
    return { status: 'converted', unit: 'kg', missing: [], value: Number((quantity * m).toPrecision(6)), method: 'unit_mass', message: `${quantity} ${unit_display} × ${m} kg/개` }
  }
  const area = AREA.includes(unit)
  if (ref === 'kg' && (area || VOLUME.includes(unit))) {
    const missing = [area && t == null && '두께', d == null && '밀도'].filter(Boolean)
    if (missing.length) return fail('needs_info', `${missing.join('·')} 입력이 필요합니다`, missing)
    return {
      status: 'converted', unit: 'kg', missing: [],
      value: Number((area ? quantity * (t / 1000) * d : quantity * d).toPrecision(6)),
      method: area ? 'area×thickness×density' : 'volume×density',
      message: area ? `${quantity} ${unit_display} × ${t} mm × ${d} kg/m³` : `${quantity} ${unit_display} × ${d} kg/m³`,
    }
  }
  return fail('incompatible', `단위 '${unit_display ?? row.raw.unit}'는 기준흐름 단위(${ref})로 환산할 수 없습니다`)
}

const summaryOf = (d, cand) => ({
  dataset_id: d.dataset_id, name: d.name, category: d.category, reference_unit: d.reference_unit,
  score: cand?.score ?? null, confidence: cand?.confidence ?? null,
  // 차단 후보나 후보 밖(직접 선택)은 사람이 정한 선택이다
  manual: cand ? cand.veto != null : true,
})

// A02 GET /api/sessions/{id}
export const getSession = (id) => (id === session.session_id ? [200, session] : notFound())

// A03 PATCH /api/sessions/{id}/rows/{row} — 보낸 필드만 반영. 실패하면 아무것도 바꾸지 않는다
export const updateRow = (id, rowId, patch = {}) => {
  if (id !== session.session_id) return notFound()
  const current = session.rows.find((r) => r.id === Number(rowId))
  if (!current) return rowNotFound()
  const row = structuredClone(current)

  if ('thickness_mm' in patch) {
    if (!(patch.thickness_mm > 0 && patch.thickness_mm <= 1000)) return [400, { detail: '두께는 0 초과 1000 이하(mm)여야 합니다.' }]
    row.overrides.thickness_mm = patch.thickness_mm
  }
  if ('density_kg_m3' in patch) {
    if (!(patch.density_kg_m3 > 0)) return [400, { detail: '밀도는 0보다 커야 합니다(kg/m³).' }]
    row.overrides.density_kg_m3 = patch.density_kg_m3
  }
  if ('unit_mass_kg' in patch) {
    if (!(patch.unit_mass_kg > 0 && patch.unit_mass_kg <= 1000)) return [400, { detail: '개당 중량은 0 초과 1000 이하(kg/개)여야 합니다.' }]
    row.overrides.unit_mass_kg = patch.unit_mass_kg
  }
  if (patch.clear_selection) Object.assign(row, { selected_id: null, selected: null, conversion: null })
  if ('selected_id' in patch) {
    const cand = row.candidates.find((x) => x.dataset_id === patch.selected_id)
    const dataset = cand ?? pool.items.find((x) => x.dataset_id === patch.selected_id)
    if (!dataset) return [400, { detail: `알 수 없는 데이터셋 ID: ${patch.selected_id}`, code: 'UNKNOWN_DATASET' }]
    row.selected_id = dataset.dataset_id
    row.selected = summaryOf(dataset, cand)
  }
  // 승인된 행의 선택을 승인 없이 바꾸면 승인은 풀린다 (승인한 데이터셋과 현재 선택이 어긋나지 않게)
  if (row.review.status === 'approved' && !patch.review_status && row.selected_id !== current.selected_id) row.review.status = 'pending'
  // 선택이나 두께·밀도가 바뀌면 선택된 데이터셋 기준으로 다시 계산한다
  if (row.selected && ['selected_id', 'thickness_mm', 'density_kg_m3', 'unit_mass_kg'].some((k) => k in patch)) {
    row.conversion = convert(row, row.selected.reference_unit)
  }
  if ('note' in patch) row.review.note = patch.note
  if (patch.review_status) {
    if (patch.review_status === 'approved' && !['ok', 'converted'].includes(row.conversion?.status)) {
      const why = row.selected ? row.conversion.message : '데이터셋을 선택하지 않았습니다'
      return [409, { detail: `단위 환산이 완료되지 않아 승인할 수 없습니다: ${why}.`, code: 'CONVERSION_INCOMPLETE' }]
    }
    row.review.status = patch.review_status
  }
  row.explanation = null // 상태가 바뀌면 근거 설명은 다시 만들어야 한다

  session.rows = session.rows.map((r) => (r === current ? row : r))
  return [200, { row, summary: summarize(session.rows) }]
}

// A04 POST /api/sessions/{id}/rows/{row}/explain — 규칙 기반 문장만. 선택된 후보의 reasons 를 그대로 쓴다
export const explainRow = (id, rowId) => {
  if (id !== session.session_id) return notFound()
  const current = session.rows.find((r) => r.id === Number(rowId))
  if (!current) return rowNotFound()
  const cand = current.candidates.find((c) => c.dataset_id === current.selected_id)
  const text = !current.selected ? '선택된 데이터셋이 없습니다.'
    : !cand ? `${current.selected.name}은(는) 후보 밖에서 직접 선택한 데이터셋입니다.`
      : cand.reasons.length ? `${cand.name} 선택 근거: ${cand.reasons.join(', ')}.` : `${cand.name}에 기록된 근거가 없습니다.`
  const explanation = {
    source: 'rule', text,
    questions: (current.conversion?.missing ?? []).map((m) => `${m} 값을 확인해 주세요`),
  }
  session.rows = session.rows.map((r) => (r === current ? { ...r, explanation } : r))
  return [200, explanation]
}

const csvCell = (v) => `"${String(v ?? '').replaceAll('"', '""')}"`

// A07 GET /api/sessions/{id}/export — mock은 CSV만. 실제 xlsx는 백엔드에서
// 오류도 실제처럼 Blob 본문으로 준다 (responseType 'blob' 요청의 오류 본문은 Blob)
export const exportSession = (id) => {
  if (id !== session.session_id) return notFound()
  const approved = session.rows.filter((r) => r.review.status === 'approved')
  if (!approved.length) {
    const body = { detail: '승인된 항목이 없습니다. 먼저 항목을 검토·승인해 주세요.', code: 'NO_APPROVED_ROWS' }
    return [409, new Blob([JSON.stringify(body)], { type: 'application/json' })]
  }
  const lines = [['원본 행', '품명', '규격', '수량', '단위', '데이터셋 ID', '데이터셋', '환산 값', '환산 단위', '메모']]
  for (const r of approved) {
    lines.push([r.source_row, r.raw.name, r.raw.spec, r.raw.quantity, r.raw.unit, r.selected_id, r.selected.name, r.conversion.value, r.conversion.unit, r.review.note])
  }
  // 맨 앞의 BOM 문자: 엑셀에서 한글이 깨지지 않게
  return [200, new Blob(['﻿' + lines.map((l) => l.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' })]
}
