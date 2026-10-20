import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { getSession } from '@/api/sessions'
import Info from '@/components/Info'
import terms from '@/terms'
import { forgetSession, readRecent } from './recentSessions'
import { LEVELS, SMALL_N, sessionStats } from './sessionStats'

const pct = (v) => (v == null ? '-' : `${(v * 100).toFixed(1)}%`)
const when = (iso) => new Date(iso).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })

// 탭 1 카드 제목·부제 (U11): 제목은 평가 용어, 부제는 쉬운 말 한 줄
const TITLES = {
  level: ['신뢰도 등급 분포', '도구가 매긴 등급별 품목 수'],
  work: ['검토 결과 분포', '품목마다 처리 결과 하나'],
  table: ['신뢰도 등급별 Top-1 채택률', '승인한 품목 중 1순위를 그대로 받은 비율 · 정답률 아님'],
}

const LEVEL_BARS = [['높음', 'approve'], ['보통', 'choose'], ['낮음', 'find'], ['none', 'gray']]
const LEVEL_NAMES = { 높음: '높음', 보통: '보통', 낮음: '낮음', none: '맞는 후보 없음' }
const WORK_BARS = [
  ['asIs', '1순위 승인', 'approve'], ['other', '후보 비교 선택', 'choose'], ['manual', '수동 탐색', 'find'],
  ['none', '미매칭·제외·반려', 'gray'], ['pending', '미검토', 'pend'],
]

// 막대 한 줄(쌓은 막대) + 범례. items: [[key, 이름, 색 클래스]], counts: { key: 행 수 }
const Stack = ({ title, sub, items, counts, total }) => (
  <section className="pf-card" aria-label={title}>
    <h2>{title}</h2>
    <p className="pf-card-sub">{sub}</p>
    <div className="pf-hw-bar pf-stack" role="img" aria-label={`${title}. ${items.map(([k, name]) => `${name} ${counts[k]}행`).join(', ')}`}>
      {items.filter(([k]) => counts[k] > 0).map(([k, , cls]) => (
        <span key={k} className={`pf-hw-${cls}`} style={{ flexGrow: counts[k] }} title={`${counts[k]}행`}>
          {total > 0 && counts[k] / total >= 0.08 && `${counts[k]}행`}
        </span>
      ))}
    </div>
    <ul className="pf-hw-legend pf-stack-legend">
      {items.map(([k, name, cls]) => (
        <li key={k}><i className={`pf-sw pf-hw-${cls}`} aria-hidden="true" /><span><b>{name}</b>{counts[k]}행</span></li>
      ))}
    </ul>
  </section>
)

// 탭 1: 내가 올린 BOM. A02 의 rows 로 센 값만 보여 준다. 정답이 없어 정답률·정확도는 계산하지 않는다 (U9 2절)
const MyBomTab = () => {
  const [recent, setRecent] = useState(readRecent)
  const [id, setId] = useState(() => recent[0]?.id ?? '')
  const [state, setState] = useState({ id: null }) // { id, rows } | { id, message }
  const [expired, setExpired] = useState(false) // 방금 만료된 작업을 목록에서 뺐다

  useEffect(() => {
    if (!id) return
    let ignore = false
    getSession(id)
      .then((data) => !ignore && setState({ id, rows: data.rows }))
      .catch((e) => {
        if (ignore) return
        if (e.status === 404) {
          forgetSession(id)
          const left = readRecent()
          setRecent(left)
          setId(left[0]?.id ?? '')
          setState({ id: null })
          setExpired(true)
        } else {
          setState({ id, message: e.status === 409 && e.code === 'JOB_NOT_FINISHED' ? '아직 처리 중입니다.' : e.detail })
        }
      })
    return () => { ignore = true }
  }, [id])

  const loaded = state.id === id
  const stats = loaded && state.rows ? sessionStats(state.rows) : null
  const small = stats && stats.approved < SMALL_N ? `승인 ${stats.approved}건 기준, 참고용` : null

  return (
    <>
      {expired && <p className="err" role="alert">이 작업은 만료되었습니다. 다시 올려 주세요. <Link to="/upload">업로드 화면</Link></p>}
      {recent.length > 0 && (
        <label className="pf-pick">작업 고르기
          <select className="inp" value={id} onChange={(e) => { setId(e.target.value); setExpired(false); setState({ id: null }) }}>
            {recent.map((s) => <option key={s.id} value={s.id}>{s.filename} · {s.total}행 · {when(s.at)}</option>)}
          </select>
        </label>
      )}

      <div className="pf-notice" role="note">
        <b>{terms.no_ground_truth.label}</b>
        <p>이 BOM에는 정답이 없어 정답률은 계산하지 않았습니다. 아래 'Top-1 채택률'은 사람이 받아들인 비율이지 정답률이 아닙니다. 정답을 아는 시험 결과는 옆 탭을 보세요.</p>
      </div>

      {recent.length === 0 && !expired && (
        <p className="pf-empty">아직 올린 BOM이 없습니다. <Link to="/upload">업로드 화면</Link>에서 BOM을 올리면 여기에 결과가 나타납니다.</p>
      )}
      {id && !loaded && <p role="status">작업 결과를 불러오는 중입니다…</p>}
      {loaded && state.message && <p className="err" role="alert">{state.message}</p>}

      {stats && (
        <>
          <div className="pf-kpis">
            <div className="pf-kpi pf-kpi-a">
              <h3>업로드 품목 수</h3>
              <p className="pf-kpi-v"><span className="num">{stats.uploaded}</span></p>
              <p className="pf-kpi-n">검토 대상 {stats.target}건</p>
            </div>
            <div className="pf-kpi pf-kpi-b">
              <h3>{terms.confidence.label} "높음" 비율<Info term="confidence" /></h3>
              <p className="pf-kpi-v"><span className="num">{pct(stats.highRate)}</span></p>
              <p className="pf-kpi-n">대상 {stats.target}건 중 {stats.levels['높음']}건</p>
            </div>
            <div className="pf-kpi pf-kpi-a">
              <h3>{terms.approve_match.label}<Info term="approve_match" /></h3>
              <p className="pf-kpi-v"><span className="num">{pct(stats.asIsRate)}</span></p>
              <p className="pf-kpi-n">승인 {stats.approved}건 중 {stats.work.asIs}건 · 정답률 아님{small && ' · 참고용'}</p>
            </div>
            <div className="pf-kpi pf-kpi-b">
              <h3>미검토 건수</h3>
              <p className="pf-kpi-v"><span className="num">{stats.work.pending}</span></p>
              <p className="pf-kpi-n">대상 {stats.target}건 중</p>
            </div>
          </div>

          <Stack title={TITLES.level[0]} sub={TITLES.level[1]} items={LEVEL_BARS.map(([k, cls]) => [k, LEVEL_NAMES[k], cls])} counts={stats.levels} total={stats.target} />
          <Stack title={TITLES.work[0]} sub={TITLES.work[1]} items={WORK_BARS} counts={stats.work} total={stats.target} />

          <section className="pf-card" aria-label={TITLES.table[0]}>
            <h2>{TITLES.table[0]}<Info term="approve_match" /></h2>
            <p className="pf-card-sub">{TITLES.table[1]}</p>
            <table className="pf-tbl">
              <thead><tr><th>신뢰도</th><th>승인한 품목</th><th>1순위 승인</th><th>비율</th></tr></thead>
              <tbody>
                {LEVELS.map((l) => {
                  const v = stats.byLevel[l]
                  return (
                    <tr key={l}>
                      <th scope="row">{l}</th>
                      <td className="num">{v.approved}</td>
                      <td className="num">{v.asIs}</td>
                      <td className="num">{pct(v.rate)}{v.approved > 0 && v.approved < SMALL_N && ` (승인 ${v.approved}건 기준, 참고용)`}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>
        </>
      )}
    </>
  )
}

export default MyBomTab
