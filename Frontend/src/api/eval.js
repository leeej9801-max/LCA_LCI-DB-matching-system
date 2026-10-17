import client from '@/api/client'

export const listEvalRuns = () => client.get('/eval/runs').then((r) => r.data) // A19

export const getEvalRun = (id) => client.get(`/eval/runs/${encodeURIComponent(id)}`).then((r) => r.data) // A14
