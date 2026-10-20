// 신뢰도 3칸 막대 + 단어 (U7 규칙 4). 높음 ■■■ / 보통 ■■□ / 낮음 ■□□. 값이 없으면 "—"
const LEVELS = { 높음: 3, 보통: 2, 낮음: 1 }

const ConfBar = ({ level }) => {
  const n = LEVELS[level]
  if (!n) return <span className="conf-none">—</span>
  return (
    <span className="conf">
      <span className="conf-bar" aria-hidden="true">{[1, 2, 3].map((i) => <i key={i} className={i <= n ? 'on' : undefined} />)}</span>
      <span>{level}</span>
    </span>
  )
}

export default ConfBar
