import client from '@/api/client'

export const searchDatasets = (params) => client.get('/datasets', { params }).then((r) => r.data) // A05

export const getDataset = (id) => client.get(`/datasets/${encodeURIComponent(id)}`).then((r) => r.data) // A06
