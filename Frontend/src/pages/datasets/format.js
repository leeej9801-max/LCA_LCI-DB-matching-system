// null·undefined는 "—"로. 0과 빈 문자열은 그대로 둔다 (측정 전과 0을 구분)
export const dash = (v) => v ?? '—'

// "기관 · 연도 · v버전" (버전이 null이면 생략)
export const orgYearVersion = ({ org, year, version }) =>
  [dash(org), dash(year), version != null && `v${version}`].filter(Boolean).join(' · ')

// 연결 실패(응답 없음) 또는 5xx 일 때 붙이는 안내. 개발 서버 프록시는 백엔드가 꺼져 있으면 빈 본문의 500을 돌려준다
export const serverHint = (error) =>
  error.status == null || error.status >= 500 ? '백엔드(127.0.0.1:8000)가 켜져 있는지 확인하세요.' : null

const OLD_YEARS = 10 // 경과 연수가 이 이상이면 "오래된 데이터" 글자를 붙인다 (색 경고 아님)

// 데이터 품질 줄: [이름, 값] 목록 (U7 규칙 10). 기준연도는 항상, 지역·할당·컷오프·기술 요약은 값이 있는 것만 따로,
// 값이 없는 것은 "그 밖의 항목: 정보 없음" 한 줄로 묶는다. 경과 연수는 표시용으로 오늘 날짜에서 센다
export const qualityRows = (d) => {
  const age = d.year == null ? null : new Date().getFullYear() - d.year
  const rows = [['기준연도', `${dash(d.year)}${age != null ? ` (${age <= 0 ? '올해' : `${age}년 전`})` : ''}${age != null && age >= OLD_YEARS ? ' · 오래된 데이터' : ''}`]]
  const others = [['지역', d.geography], ['할당', d.allocation], ['컷오프', d.cutoff], ['기술 요약', d.tech_summary]]
  rows.push(...others.filter(([, v]) => v != null))
  if (others.some(([, v]) => v == null)) rows.push(['그 밖의 항목', '정보 없음'])
  return rows
}


// 배출계수(carbon) 표시용 (X1). 유효숫자 3자리, 지수 표기 없음: 0.98384 → "0.984", 0.00854434 → "0.00854"
export const sig3 = (v) => Number(v).toLocaleString('en-US', { maximumSignificantDigits: 3, useGrouping: false })
export const carbonUnit = (c) => `${c.unit}/${c.per ?? '기준 단위'}`

// 기관 이름은 표에서 괄호 안 소속을 뺀다: "환경부(한국환경산업기술원)" → "환경부"
export const shortOrg = (org) => (org == null ? '—' : org.replace(/\(.*\)/, '').trim() || org)
