// 성능 확인 화면의 차트. 새 의존성 없이 SVG·CSS 로 그린다. 값과 개수는 마크 옆에 직접 적고, 축은 0~100% 고정.
// 색: 검정 = 고른 데이터, 하늘색 = 비교 데이터 (eval.css 의 변수)
const W = 388
const X0 = 36 // 축 글자 폭만큼 비운 왼쪽
const Y0 = 192 // 0% 의 y
const H = 160 // 0~100% 높이
const y = (v) => Y0 - v * H
const pct = (v) => (v === 1 ? '100%' : `${(v * 100).toFixed(1)}%`)

const Grid = () => (
  <g className="pf-grid">
    {[0, 0.25, 0.5, 0.75, 1].map((v) => (
      <g key={v}>
        <line x1={X0} x2={W} y1={y(v)} y2={y(v)} />
        <text x="0" y={y(v) + 4}>{v * 100}%</text>
      </g>
    ))}
  </g>
)

// 묶은 세로 막대. groups: [{ label, a: { v, n }, b?: { v, n } }] (b 가 없으면 막대 하나)
export const GroupedBars = ({ groups, aria }) => {
  const step = (W - X0) / groups.length
  return (
    <svg className="pf-svg" viewBox="0 0 388 240" role="img" aria-label={aria}>
      <Grid />
      {groups.map((g, i) => {
        const c = X0 + step * (i + 0.5)
        return (
          <g key={g.label}>
            {[[g.a, 'a'], [g.b, 'b']].filter(([s]) => s).map(([s, k], j, all) => [s, c - (all.length * 34 - 6) / 2 + j * 34, k]).map(([s, x, k]) => (
              <g key={k} className={`pf-${k}`}>
                <rect x={x} y={y(s.v) - (s.v === 0 ? 2 : 0)} width="28" height={Math.max(s.v * H, 2)} rx="3" />
                <text className="pf-val" x={x + 14} y={y(s.v) - (s.v === 0 ? 6 : 4)} textAnchor="middle">{pct(s.v)}</text>
              </g>
            ))}
            <text className="pf-axis" x={c} y="212" textAnchor="middle">{g.label}</text>
            <text className="pf-sub" x={c} y="230" textAnchor="middle">{g.b ? `${g.a.n} · ${g.b.n}개` : `${g.a.n}개`}</text>
          </g>
        )
      })}
    </svg>
  )
}

// 꺾은선. xs: 가로 눈금 글자, a·b: 0~1 값 배열(b 는 없을 수 있다). 값 글자는 두 점 중 높은 쪽 위, 낮은 쪽 아래에 둔다
export const LineChart = ({ xs, a, b, xLabel, aria }) => {
  const px = (i) => 56 + (i * (368 - 56)) / (xs.length - 1) // 첫 점 x=56, 끝 점 x=368
  const line = (vs) => vs.map((v, i) => `${i ? 'L' : 'M'}${px(i)} ${y(v)}`).join(' ')
  return (
    <svg className="pf-svg" viewBox="0 0 388 240" role="img" aria-label={aria}>
      <Grid />
      {[[b, 'b'], [a, 'a']].filter(([vs]) => vs).map(([vs, k]) => (
        <g key={k} className={`pf-${k}`}>
          <path className="pf-line" d={line(vs)} />
          {vs.map((v, i) => {
            const other = (k === 'a' ? b : a)?.[i]
            const above = other == null || v > other || (v === other && k === 'a')
            return (
              <g key={i}>
                <circle cx={px(i)} cy={y(v)} r="4" />
                <text className="pf-val" x={px(i)} y={y(v) + (above ? -10 : 18)} textAnchor="middle">{pct(v)}</text>
              </g>
            )
          })}
        </g>
      ))}
      {xs.map((t, i) => <text key={t} className="pf-axis" x={px(i)} y="212" textAnchor="middle">{t}</text>)}
      <text className="pf-sub" x={(56 + 368) / 2} y="230" textAnchor="middle">{xLabel}</text>
    </svg>
  )
}

// 작은 도넛: part/total 만큼 색을 칠하고 가운데에 "part/total"
export const Donut = ({ part, total, cls, aria }) => {
  const r = 42
  const len = 2 * Math.PI * r
  return (
    <svg className={`pf-donut ${cls}`} viewBox="0 0 96 96" role="img" aria-label={aria}>
      <circle className="pf-track" cx="48" cy="48" r={r} />
      <circle className="pf-arc" cx="48" cy="48" r={r} strokeDasharray={`${(total ? part / total : 0) * len} ${len}`} transform="rotate(-90 48 48)" />
      <text x="48" y="54" textAnchor="middle">{part}/{total}</text>
    </svg>
  )
}
