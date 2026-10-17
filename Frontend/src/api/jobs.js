import client from '@/api/client'

export const getJob = (id) => client.get(`/jobs/${encodeURIComponent(id)}`).then((r) => r.data) // A21
