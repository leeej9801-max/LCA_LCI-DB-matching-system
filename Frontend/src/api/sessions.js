import client from '@/api/client'

const base = (id) => `/sessions/${encodeURIComponent(id)}`

const withFile = (file, extra = {}) => {
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(extra)) if (v != null) form.append(k, v)
  return form
}

export const previewUpload = (file) => client.post('/sessions/preview', withFile(file)).then((r) => r.data) // A20

// mapping: { 품명: '부품명', ... } 자동 인식을 덮어쓸 때만. 응답은 202 { job_id, session_id }
export const createSession = (file, mapping) =>
  client.post('/sessions', withFile(file, { mapping: mapping && JSON.stringify(mapping) })).then((r) => r.data) // A01

export const getSampleCsv = () => client.get('/sample.csv', { responseType: 'blob' }).then((r) => r.data) // A08

export const getTemplate = () => client.get('/template.xlsx', { responseType: 'blob' }).then((r) => r.data) // A08b

export const getSession = (id) => client.get(base(id)).then((r) => r.data) // A02

export const updateRow = (id, rowId, patch) => client.patch(`${base(id)}/rows/${encodeURIComponent(rowId)}`, patch).then((r) => r.data) // A03

export const explainRow = (id, rowId) => client.post(`${base(id)}/rows/${encodeURIComponent(rowId)}/explain`).then((r) => r.data) // A04

export const exportSession = (id, format = 'csv') => client.get(`${base(id)}/export`, { params: { format }, responseType: 'blob' }).then((r) => r.data) // A07
