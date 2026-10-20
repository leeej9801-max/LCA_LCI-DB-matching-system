import sample from './data/session.mock.json'
import { createJob } from './jobs'

const MAX_BYTES = 5 * 1024 * 1024
const MAX_ROWS = 2000
// 화면의 "샘플로 해 보기"가 만드는 파일 이름. mock은 이 이름이면 미리 계산된 결과로 본다
const SAMPLE_NAME = '부품BOM_샘플.csv'

// [필드, 필수, 헤더 별칭(소문자·공백 없이)]
const FIELDS = [
  ['품명', true, ['품명', '부품명', '자재명', 'partname']],
  ['규격', false, ['규격', '사양', 'spec']],
  ['단위', true, ['단위', 'unit']],
  ['수량', true, ['수량', '소요량', 'qty']],
]
const norm = (s) => s.toLowerCase().replace(/\s+/g, '')

// 따옴표 안의 쉼표·줄바꿈·""를 처리하는 작은 CSV 파서. 빈 줄은 버린다
// shortcut: 쉼표 구분 UTF-8만 읽는다. 세미콜론·탭 구분은 백엔드 파서(T9)에서
export const parseCsv = (text) => {
  const rows = []
  let row = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c !== '"') cell += c
      else if (text[i + 1] === '"') { cell += '"'; i++ }
      else quoted = false
    } else if (c === '"') quoted = true
    else if (c === ',') { row.push(cell); cell = '' }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(cell); rows.push(row); row = []; cell = ''
    } else cell += c
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row) }
  return rows.filter((r) => r.some((v) => v.trim() !== ''))
}

// 헤더 별칭으로 4필드에 대응. override: { 필드: 파일 컬럼명 } (A01 mapping)
export const detectMapping = (columns, rows, override = {}) =>
  FIELDS.map(([field, required, aliases]) => {
    const manual = columns.includes(override[field]) ? override[field] : null
    const source = manual ?? columns.find((c) => aliases.includes(norm(c))) ?? null
    const k = columns.indexOf(source)
    return { field, required, source, method: manual ? 'manual' : source ? 'auto' : 'missing', sample: k >= 0 ? rows[0]?.[k] ?? null : null }
  })

// 파일 검사 공통(A20·A01): 크기 → 형식 → 행 수. 실패하면 { error: [status, body] }
const readUpload = async (form) => {
  const file = form.get('file')
  if (!(file instanceof File)) return { error: [400, { detail: '파일을 읽을 수 없습니다. CSV 또는 XLSX 파일인지 확인해 주세요.', code: 'UNREADABLE_FILE' }] }
  if (file.size > MAX_BYTES) return { error: [413, { detail: '파일은 5MB 이하여야 합니다.', code: 'FILE_TOO_LARGE' }] }
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return { error: [400, { detail: 'mock에서는 CSV만 읽습니다. 샘플로 해 보기를 쓰세요.', code: 'UNREADABLE_FILE' }] }
  }
  const [columns, ...rows] = parseCsv((await file.text()).replace(/^\uFEFF/, ''))
  if (!columns || rows.length === 0) return { error: [400, { detail: '파일을 읽을 수 없습니다. CSV 또는 XLSX 파일인지 확인해 주세요.', code: 'UNREADABLE_FILE' }] }
  if (rows.length > MAX_ROWS) {
    return { error: [400, { detail: `행이 너무 많습니다(${rows.length.toLocaleString('en-US')}행). 한 번에 2,000행까지 올릴 수 있습니다.`, code: 'TOO_MANY_ROWS', meta: { rows: rows.length, limit: MAX_ROWS } }] }
  }
  return { name: file.name, columns: columns.map((c) => c.trim()), rows }
}

// A20 POST /api/sessions/preview
export const previewUpload = async (params, form) => {
  const r = await readUpload(form)
  if (r.error) return r.error
  return [200, {
    filename: r.name,
    rows_total: r.rows.length,
    rows_skipped: { example: 0, empty_name: 0 },
    column_mapping: detectMapping(r.columns, r.rows),
    file_columns: r.columns,
    preview_rows: r.rows.slice(0, 5).map((row) => r.columns.map((_, i) => row[i] ?? '')),
  }]
}

// mock 전용: 파일 이름으로 429·작업 실패를 일으켜 `다시 시도` 경로를 시험한다. 새로고침하면 초기화
const queueFullSeen = new Set()
const jobFailSeen = new Set()

const eulReul = (w) => ((w.charCodeAt(w.length - 1) - 0xac00) % 28 ? '을' : '를')

// A01 POST /api/sessions — mock은 실제 매칭을 하지 않고 예시 세션으로 간다 (202 + job_id)
export const createSession = async (params, form) => {
  const r = await readUpload(form)
  if (r.error) return r.error
  let override
  try {
    override = JSON.parse(form.get('mapping') ?? '{}')
  } catch {
    return [400, { detail: 'mapping은 JSON 문자열이어야 합니다.' }]
  }
  const missing = detectMapping(r.columns, r.rows, override).filter((m) => m.required && !m.source).map((m) => m.field)
  if (missing.length) {
    const last = missing[missing.length - 1]
    return [400, { detail: `필수 컬럼 ${missing.map((m) => `'${m}'`).join(', ')}${eulReul(last)} 찾지 못했습니다.`, code: 'MISSING_COLUMN', meta: { missing } }]
  }
  if (r.name.includes('queue-full') && !queueFullSeen.has(r.name)) {
    queueFullSeen.add(r.name)
    return [429, { detail: '지금 처리 중인 작업이 많습니다. 잠시 후 다시 시도해 주세요.', code: 'QUEUE_FULL' }]
  }
  const fail = r.name.includes('job-fail') && !jobFailSeen.has(r.name)
  if (fail) jobFailSeen.add(r.name)
  return [202, { job_id: createJob({ instant: r.name === SAMPLE_NAME, sessionId: sample.session_id, fail }), session_id: sample.session_id }]
}

const csvCell = (v) => `"${String(v ?? '').replaceAll('"', '""')}"`

// A08 GET /api/sample.csv — 예시 세션 행의 raw 4필드. 샘플로 해 보기 결과와 내용이 같다
export const getSampleCsv = () => {
  const lines = [['품명', '규격', '단위', '수량'], ...sample.rows.map((r) => [r.raw.name, r.raw.spec, r.raw.unit, r.raw.quantity])]
  // 맨 앞의 BOM 문자: 엑셀에서 한글이 깨지지 않게
  return [200, new Blob(['\uFEFF' + lines.map((l) => l.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' })]
}
