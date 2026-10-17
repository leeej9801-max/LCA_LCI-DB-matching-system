import client from '@/api/client'

const base = (id) => `/sessions/${encodeURIComponent(id)}`

export const getSession = (id) => client.get(base(id)).then((r) => r.data) // A02

export const updateRow = (id, rowId, patch) => client.patch(`${base(id)}/rows/${encodeURIComponent(rowId)}`, patch).then((r) => r.data) // A03

export const explainRow = (id, rowId) => client.post(`${base(id)}/rows/${encodeURIComponent(rowId)}/explain`).then((r) => r.data) // A04

export const exportSession = (id, format = 'csv') => client.get(`${base(id)}/export`, { params: { format }, responseType: 'blob' }).then((r) => r.data) // A07
