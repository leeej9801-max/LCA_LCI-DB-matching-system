// null·undefined는 "—"로. 0과 빈 문자열은 그대로 둔다 (측정 전과 0을 구분)
export const dash = (v) => v ?? '—'

// "기관 · 연도 · v버전" (버전이 null이면 생략)
export const orgYearVersion = ({ org, year, version }) =>
  [dash(org), dash(year), version != null && `v${version}`].filter(Boolean).join(' · ')

// 연결 실패(응답 없음) 또는 5xx 일 때 붙이는 안내. 개발 서버 프록시는 백엔드가 꺼져 있으면 빈 본문의 500을 돌려준다
export const serverHint = (error) =>
  error.status == null || error.status >= 500 ? '백엔드(127.0.0.1:8000)가 켜져 있는지 확인하세요.' : null
