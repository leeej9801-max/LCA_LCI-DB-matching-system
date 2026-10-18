import axios from 'axios'
import mockAdapter from '@/api/mock'

// 07-API명세서 1장 오류 형식 표. 응답에 detail 문자열이 없을 때 쓴다.
const DEFAULT_DETAIL = {
  400: '요청 내용이 잘못되었습니다.',
  404: '대상을 찾을 수 없습니다.',
  409: '현재 상태에서는 할 수 없는 작업입니다.',
  413: '파일이 너무 큽니다.',
  422: '입력 형식이 올바르지 않습니다.',
  503: '일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
}

// VITE_API_MOCK=1 이면 mock, 단 VITE_API_REAL(콤마로 구분한 경로 접두사, 예 "/datasets")로 시작하는 요청은 실제 서버로.
// VITE_API_MOCK 이 없거나 0 이면 전부 실제 서버. 어댑터는 요청마다 고른다
const REAL = (import.meta.env.VITE_API_REAL ?? '').split(',').map((p) => p.trim()).filter(Boolean)
// 이 경로의 요청이 mock 으로 가는지. 환경 변수는 빌드 때 정해지므로 실행 중 바뀌지 않는다 (화면의 "예시 데이터" 줄)
export const isMock = (path) => import.meta.env.VITE_API_MOCK === '1' && !REAL.some((p) => path.startsWith(p))
const realAdapter = axios.getAdapter(axios.defaults.adapter)
const mixedAdapter = (config) => (REAL.some((p) => config.url?.startsWith(p)) ? realAdapter(config) : mockAdapter(config))

const client = axios.create({
  baseURL: '/api',
  ...(import.meta.env.VITE_API_MOCK === '1' && { adapter: mixedAdapter }),
})

// 모든 오류를 { status, detail, code, meta } 하나의 모양으로 던진다.
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status ?? null
    let body = error.response?.data ?? {}
    // responseType 'blob' 요청(내보내기)의 오류 본문은 Blob이라 글자로 읽어 JSON으로 푼다
    if (body instanceof Blob) body = await body.text().then(JSON.parse).catch(() => ({}))
    // FastAPI 422의 detail은 배열이라 화면에 그대로 못 쓴다
    const detail = typeof body.detail === 'string'
      ? body.detail
      : DEFAULT_DETAIL[status] ?? '서버에 연결하지 못했습니다.'
    return Promise.reject({ status, detail, code: body.code ?? null, meta: body.meta ?? null })
  },
)

export default client
