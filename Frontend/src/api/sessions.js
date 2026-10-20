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

// kind: 'blank'(빈 양식) | 'sample'(예시가 채워진 샘플). FTA 원산지 확인용 소요부품(자재) 명세서 xlsx
export const getBomTemplate = (kind) => client.get('/bom/template', { params: { kind }, responseType: 'blob' }).then((r) => r.data) // A08c

export const getTemplate = () => client.get('/template.xlsx', { responseType: 'blob' }).then((r) => r.data) // A08b

export const getSession = (id) => client.get(base(id)).then((r) => r.data) // A02

export const updateRow = (id, rowId, patch) => client.patch(`${base(id)}/rows/${encodeURIComponent(rowId)}`, patch).then((r) => r.data) // A03

export const explainRow = (id, rowId) => client.post(`${base(id)}/rows/${encodeURIComponent(rowId)}/explain`).then((r) => r.data) // A04

// A07. { blob, filename }: 파일명은 Content-Disposition 의 filename*(UTF-8, RFC 5987)을, 없으면 filename 을 쓴다. 헤더가 없으면(mock) filename 은 null
export const exportSession = (id, format = 'xlsx') =>
  client.get(`${base(id)}/export`, { params: { format }, responseType: 'blob' }).then((r) => {
    const cd = r.headers?.['content-disposition'] ?? ''
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd)
    const plain = /filename="?([^";]+)"?/i.exec(cd)
    return { blob: r.data, filename: star ? decodeURIComponent(star[1]) : plain ? plain[1] : null }
  })
