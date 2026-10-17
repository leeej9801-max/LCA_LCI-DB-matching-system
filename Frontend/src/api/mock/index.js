import { AxiosError } from 'axios'
import * as datasets from './datasets'
import * as sessions from './sessions'

// [메서드, 경로 패턴(baseURL '/api' 제외), 핸들러(쿼리 params, ...경로 인자, 요청 본문) → [status, body]]
const handlers = [
  ['get', /^\/datasets$/, (params) => datasets.searchDatasets(params)], // A05
  ['get', /^\/datasets\/([^/]+)$/, (params, id) => datasets.getDataset(id)], // A06
  ['get', /^\/sessions\/([^/]+)$/, (params, id) => sessions.getSession(id)], // A02
  ['patch', /^\/sessions\/([^/]+)\/rows\/([^/]+)$/, (params, id, row, body) => sessions.updateRow(id, row, body)], // A03
  ['post', /^\/sessions\/([^/]+)\/rows\/([^/]+)\/explain$/, (params, id, row) => sessions.explainRow(id, row)], // A04
  ['get', /^\/sessions\/([^/]+)\/export$/, (params, id) => sessions.exportSession(id)], // A07
]

export default async function mockAdapter(config) {
  const method = config.method
  const path = config.url.split('?')[0]
  await new Promise((resolve) => setTimeout(resolve, 300))

  let status = 404
  let data = { detail: `mock에 없는 경로: ${method.toUpperCase()} ${path}` }
  for (const [m, pattern, handle] of handlers) {
    const match = m === method && path.match(pattern)
    if (match) {
      const body = config.data ? JSON.parse(config.data) : {}
      ;[status, data] = handle(config.params ?? {}, ...match.slice(1).map(decodeURIComponent), body)
      break
    }
  }

  // 화면이 응답을 고쳐도 픽스처 원본은 그대로 두도록 복사해서 준다
  const response = { data: structuredClone(data), status, statusText: String(status), headers: {}, config, request: null }
  if (status >= 400) {
    throw new AxiosError(`mock ${status}`, AxiosError.ERR_BAD_REQUEST, config, null, response)
  }
  return response
}
