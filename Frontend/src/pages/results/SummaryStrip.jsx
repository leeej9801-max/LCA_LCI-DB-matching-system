import { summarizeRows } from './format'

// 결과 목록 위 요약 띠 (U7 2-2). 색 채움 없이 숫자만 굵게. 도구 기준(후보를 찾은 행)과 사람 기준(승인 대기)을 나눠 보여 준다.
// 정의는 format.js 의 summarizeRows 주석에 있다. 아래 "검토 진행" 막대: 초록=승인, 빨강=반려·제외
const pct = (n, total) => (total ? Math.round((n / total) * 100) : 0)

const SummaryStrip = ({ rows, statusOf }) => {
  const s = summarizeRows(rows, statusOf)
  const level = [`높음 ${s.high}`, `보통 ${s.mid}`, ...(s.low ? [`낮음 ${s.low}`] : [])].join(' · ')
  return (
    <section className="kpis" aria-label="요약">
      <div className="kpi">
        <div className="kpi-l">후보를 찾은 행</div>
        <div className="kpi-n">{s.found}<span> / {s.total}</span></div>
        <div className="kpi-s">전체의 {pct(s.found, s.total)}%</div>
      </div>
      <div className="kpi">
        <div className="kpi-l">승인 대기</div>
        <div className="kpi-n">{s.waiting}</div>
        <div className="kpi-s">{level}</div>
      </div>
      <div className="kpi">
        <div className="kpi-l">맞는 후보 없음</div>
        <div className="kpi-n">{s.none}</div>
        <div className="kpi-s">국가 DB에 맞는 데이터 없음</div>
      </div>
      <div className="kpi">
        <div className="kpi-l">단위 정보 필요</div>
        <div className="kpi-n">{s.unit}</div>
        <div className="kpi-s">승인 전에 입력</div>
      </div>
      <div className="kpi kpi-prog">
        <div className="kpi-head"><span>검토 진행</span><b>{s.done} / {s.total} 처리</b></div>
        <div className="prog-bar" aria-hidden="true">
          <i className="ok" style={{ width: `${pct(s.approved, s.total)}%` }} />
          <i className="bad" style={{ width: `${pct(s.closed, s.total)}%` }} />
        </div>
        <div className="kpi-legend"><span>승인 {s.approved}</span><span>반려·제외 {s.closed}</span><span>남음 {s.left}</span></div>
      </div>
    </section>
  )
}

export default SummaryStrip
