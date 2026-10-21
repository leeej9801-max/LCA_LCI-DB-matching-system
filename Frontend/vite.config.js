import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'url'

// 운영(real) 빌드: /eval 은 실제 서버로 가므로 평가 기록 mock(입력 글자·정답 번호가 든 json)을 번들에서 뺀다.
// import.meta.glob 은 조건문 안에 넣어도 chunk 가 남아서, 파일 자체를 빈 모듈로 바꾼다. dev·dev:real·mock 빌드는 그대로
const dropEvalMock = (command, mode) => ({
  name: 'drop-eval-mock',
  enforce: 'pre',
  load(id) {
    if (command === 'build' && mode === 'real' && id.replaceAll('\\', '/').endsWith('/src/api/mock/eval.js')) {
      return [
        "const gone = async () => [404, { detail: '평가 기록을 찾을 수 없습니다.', code: 'EVAL_RUN_NOT_FOUND' }]",
        'export const listEvalRuns = gone',
        'export const getEvalRun = gone',
      ].join('\n')
    }
  },
})

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => ({
  plugins: [dropEvalMock(command, mode), react()],
  // base: "/",
  server: {
    // host: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@pages': fileURLToPath(new URL('./src/pages', import.meta.url)),
      '@styles': fileURLToPath(new URL('./src/styles', import.meta.url)),
      '@assets': fileURLToPath(new URL('./src/assets', import.meta.url)),
      '@hooks': fileURLToPath(new URL('./src/hooks', import.meta.url)),
    }
  }
}))
