// null·undefined는 "—"로. 0과 빈 문자열은 그대로 둔다 (측정 전과 0을 구분)
export const dash = (v) => v ?? '—'

// "기관 · 연도 · v버전" (버전이 null이면 생략)
export const orgYearVersion = ({ org, year, version }) =>
  [dash(org), dash(year), version != null && `v${version}`].filter(Boolean).join(' · ')
