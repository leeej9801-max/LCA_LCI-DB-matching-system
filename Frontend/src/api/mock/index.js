import { AxiosError } from 'axios'
import * as datasets from './datasets'
import * as jobs from './jobs'
import * as sessions from './sessions'
import * as upload from './upload'

// [메서드, 경로 패턴(baseURL '/api' 제외), 핸들러(쿼리 params, ...경로 인자, 요청 본문) → [status, body] (Promise도 가능)]
// 요청 본문은 JSON 객체, 업로드(A20·A01)는 FormData 그대로
const handlers = [
  ['post', /^\/sessions\/preview$/, (params, form) => upload.previewUpload(params, form)], // A20
  ['post', /^\/sessions$/, (params, form) => upload.createSession(params, form)], // A01
  ['get', /^\/jobs\/([^/]+)$/, (params, id) => jobs.getJob(id)], // A21
  ['get', /^\/sample\.csv$/, () => upload.getSampleCsv()], // A08
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
      const body = config.data instanceof FormData ? config.data : config.data ? JSON.parse(config.data) : {}
      ;[status, data] = await handle(config.params ?? {}, ...match.slice(1).map(decodeURIComponent), body)
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
