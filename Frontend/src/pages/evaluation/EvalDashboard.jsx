import { useState } from 'react'
import Info from '@/components/Info'
import terms from '@/terms'
import { Donut, GroupedBars, LineChart } from './Charts'
import { DROPPED, ERROR_TYPES, GOAL_OVER_NOTE, HIGH_COVERAGE_GOAL, HIGH_ERROR_GOAL, HUMAN_WORK, METHODS_NOTE, METHOD_SUBS, NEXT, NOTICE_BODY, NOTICE_TITLE, NO_ANSWER_NOTE, STYLE_NOTE, TITLES, UNKNOWN } from './evalText'
import { LEVELS, METHODS, RECALL_KS, goalOf, humanWork } from './pick'

const BADGES = { full: ['ok', '목표 충족'], partial: ['mid', '일부만 충족'], miss: ['bad', '목표 미달'] }

const pct = (v) => (v === 1 ? '100%' : `${(v * 100).toFixed(1)}%`)
const range = ([lo, hi]) => `${(lo * 100).toFixed(1)}~${(hi * 100).toFixed(1)}%`
const count = (rate, n) => Math.round(rate * n)

// 큰 숫자 칸. 고른 데이터 값이 크고, 아래 줄에 비교 데이터 값을 둔다
const Kpi = ({ tone, title, info, value, badge, of, extra, cmpName, cmpValue }) => (
  <div className={`pf-kpi pf-kpi-${tone}`}>
    <h3>{title}{info}</h3>
    <p className="pf-kpi-v"><span className="num">{value}</span>{badge}</p>
    <p className="pf-kpi-n">{of}</p>
    {extra}
    {cmpName && <p className="pf-kpi-c"><i className="pf-dot pf-dot-b" aria-hidden="true" />{cmpName}<span className="pf-rule" aria-hidden="true" /><b className="num">{cmpValue}</b></p>}
  </div>
)

const Legend = ({ a, b }) => (
  <p className="pf-legend"><span><i className="pf-dot pf-dot-a" aria-hidden="true" />{a}</span>{b && <span><i className="pf-dot pf-dot-b" aria-hidden="true" />{b}</span>}</p>
)

// 카드: 제목(평가 용어, 굵게) + 부제(쉬운 말 한 줄, 회색). 제목에 ⓘ 를 붙일 수 있다
const Card = ({ title, sub, info, children }) => (
  <section className="pf-card" aria-label={title}>
    <h2>{title}{info}</h2>
    {sub && <p className="pf-card-sub">{sub}</p>}
    {children}
  </section>
)

const CiLine = ({ ci, over }) => (
  <p className="pf-kpi-ci">{terms.ci95.label} {range(ci)}<Info term="ci95" />{over && ` · ${GOAL_OVER_NOTE}`}</p>
)

// 평가 한 건의 결과: 값은 모두 pick.js 가 리포트에서 고른 것. sel = 고른 데이터, cmp = 비교 데이터(없을 수 있다), p1 = 공개 문서 표기 데이터
const EvalDashboard = ({ sel, cmp, selName, cmpName, p1, kind }) => {
  const [open, setOpen] = useState(false)
  const sets = [[selName, sel, 'a'], ...(cmp ? [[cmpName, cmp, 'b']] : [])]
  const hw = sets.map(([, p]) => humanWork(p))
  const hwAria = sets.map(([name], i) => `${name}: ${HUMAN_WORK.map((w) => `${w.title} 약 ${hw[i][w.key]}건`).join(', ')}`).join('. ')
  const goal = goalOf(sel)
  const [badgeCls, badgeText] = BADGES[goal.badge]
  const base = METHODS.indexOf(sel.pairBase) // 새로 맞힘·틀림은 이 방식(방식 B) 기준

  return (
    <>
      <details className="pf-notice" open>
        <summary>{NOTICE_TITLE}</summary>
        <p>{NOTICE_BODY[kind]}</p>
      </details>

      <div className="pf-kpis">
        <Kpi
          tone="a" title={terms.top1_rate.label} info={<Info term="top1_rate" />} value={pct(sel.top1)} of={`정답 있는 ${sel.answerable}건 중 ${count(sel.top1, sel.answerable)}건`}
          cmpName={cmp && cmpName} cmpValue={cmp && pct(cmp.top1)}
        />
        <Kpi
          tone="b" title={terms.top3_rate.label} info={<Info term="top3_rate" />} value={pct(sel.top3)} of={`정답 있는 ${sel.answerable}건 중 ${count(sel.top3, sel.answerable)}건`}
          cmpName={cmp && cmpName} cmpValue={cmp && pct(cmp.top3)}
        />
        <Kpi
          tone="a" title={`${terms.confidence.label} "높음" 비율`} info={<Info term="confidence" />} value={pct(sel.highCoverage)} of={`전체 ${sel.total}건 중 ${sel.highRows}건 · 목표 ${HIGH_COVERAGE_GOAL * 100}% 이상`}
          extra={<CiLine ci={sel.highCoverageCi} />}
          cmpName={cmp && cmpName} cmpValue={cmp && pct(cmp.highCoverage)}
        />
        <Kpi
          tone="b" title={'"높음" 오답률'} value={pct(sel.highError)}
          badge={<span className={`pf-badge ${badgeCls}`}>{badgeText}</span>}
          of={`${sel.highRows}건 중 ${count(sel.highError, sel.highRows)}건 · 목표 ${HIGH_ERROR_GOAL * 100}% 이하`}
          extra={(
            <>
              {goal.badge === 'partial' && <p className="pf-kpi-ci">확신한 추천 비율이 목표({HIGH_COVERAGE_GOAL * 100}%)에 못 미칩니다</p>}
              <CiLine ci={sel.highErrorCi} over={goal.rangeOver} />
            </>
          )}
          cmpName={cmp && cmpName} cmpValue={cmp && pct(cmp.highError)}
        />
      </div>

      <Card title={TITLES.work[0]} sub={TITLES.work[1]}>
        <div role="img" aria-label={hwAria}>
          {sets.map(([name], i) => (
            <div key={name} className="pf-hw-row" aria-hidden="true">
              <span className="pf-hw-name">{name}</span>
              <div className="pf-hw-bar">
                {HUMAN_WORK.filter(({ key }) => hw[i][key] > 0).map(({ key }) => (
                  <span key={key} className={`pf-hw-${key}`} style={{ flexGrow: hw[i][key] }} title={`약 ${hw[i][key]}개`}>
                    {hw[i][key] >= 8 && `약 ${hw[i][key]}개`}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <ul className="pf-hw-legend">
          {HUMAN_WORK.map(({ key, title, sub }) => (
            <li key={key}><i className={`pf-sw pf-hw-${key}`} aria-hidden="true" /><span><b>{title}</b>{sub}</span></li>
          ))}
        </ul>
        <p className="pf-foot">실제 BOM에서는 구매 부품과 회사 고유 코드가 얼마나 섞였는지에 따라 달라집니다. 값은 시험 결과에서 계산합니다.</p>
      </Card>

      <div className="pf-two">
        <Card title={TITLES.level[0]} sub={TITLES.level[1]}>
          <Legend a={selName} b={cmp && cmpName} />
          <GroupedBars
            groups={LEVELS.map((l) => ({ label: l, a: { v: sel.levels[l].acc, n: sel.levels[l].rows }, ...(cmp && { b: { v: cmp.levels[l].acc, n: cmp.levels[l].rows } }) }))}
            aria={`신뢰도 등급별 정답률. ${sets.map(([name, p]) => `${name}: ${LEVELS.map((l) => `${l} ${pct(p.levels[l].acc)}(${p.levels[l].rows}개)`).join(', ')}`).join('. ')}.`}
          />
          <p className="pf-note">확신할수록 실제로 더 잘 맞습니다. 다만 공개 문서 표기에서는 "높음"도 10개 중 {Math.round(p1.highError * 10)}개 정도 틀렸습니다.</p>
        </Card>
        <Card title={TITLES.recall[0]} sub={TITLES.recall[1]} info={<Info term="recall_k" />}>
          <Legend a={selName} b={cmp && cmpName} />
          <LineChart
            xs={RECALL_KS.map((k) => `${k}개`)} a={sel.recall} b={cmp?.recall} xLabel="볼 추천 개수"
            aria={`상위 K개 후보 안에 정답이 포함된 비율. ${sets.map(([name, p]) => `${name}: ${RECALL_KS.map((k, i) => `${k}개 ${pct(p.recall[i])}`).join(', ')}`).join('. ')}.`}
          />
          <p className="pf-note">
            {sets.map(([name, p]) => `${name}은 추천 3개 안에 ${pct(p.recall[1])}, 30개 안에 ${pct(p.recall[3])}에서 정답이 나옵니다.`).join(' ')}
            {sets.some(([, p]) => p.recall[3] < 1) && ' 30개를 봐도 나오지 않는 품목은 검색이 아예 놓친 것입니다.'}
          </p>
        </Card>
      </div>

      <div className="pf-two">
        <Card title={TITLES.errors[0]} sub={TITLES.errors[1]}>
          <p className="pf-dim">공개 문서 표기 데이터의 틀린 답을 나눠 본 결과</p>
          <table className="pf-tbl">
            <thead><tr><th>유형</th><th>예</th><th>나아질 방법</th></tr></thead>
            <tbody>
              {ERROR_TYPES.map(([type, example, fix]) => <tr key={type}><th scope="row">{type}</th><td>{example}</td><td>{fix}</td></tr>)}
            </tbody>
          </table>
        </Card>
        <Card title={TITLES.none[0]} sub={TITLES.none[1]}>
          <div className="pf-donuts">
            {sets.map(([name, p, k]) => (
              <div key={k} className="pf-na">
                <Donut
                  part={p.noAnswer.noneFound} total={p.noAnswer.noneRows} cls={`pf-${k}`}
                  aria={`${name}: 없는 품목 ${p.noAnswer.noneRows}개 중 ${p.noAnswer.noneFound}개를 "없음"으로 알림. 있는데 "없음"이라 한 품목 ${p.noAnswer.ansRows}개 중 ${p.noAnswer.ansWrong}개`}
                />
                <b>{name}</b>
                <p>없는 품목 {p.noAnswer.noneRows}개 중 {p.noAnswer.noneFound}개를 "없음"으로 알림</p>
                <p className="pf-dim">있는데 "없음"이라 한 품목: {p.noAnswer.ansRows}개 중 {p.noAnswer.ansWrong}개</p>
              </div>
            ))}
          </div>
          <p className="pf-note">{NO_ANSWER_NOTE}</p>
        </Card>
      </div>

      {sel.inputStyles.length > 0 && (
        <Card title={TITLES.style[0]} sub={TITLES.style[1]}>
          <div role="img" aria-label={`입력 유형별 Top-1 정답률. ${sel.inputStyles.map((s) => `${s.name} ${pct(s.top1)}(${s.n}개)`).join(', ')}`}>
            {sel.inputStyles.map((s) => (
              <div key={s.key} className="pf-m-row" aria-hidden="true">
                <div className="pf-m-name"><b>{s.name}</b><span className="pf-m-sub">{s.n}개</span></div>
                <div className="pf-m-bars">
                  <p className="pf-m-bar pf-a"><i style={{ width: `${s.top1 * 100}%` }} /><span className="num">{pct(s.top1)}</span></p>
                </div>
              </div>
            ))}
          </div>
          <p className="pf-note">{STYLE_NOTE}</p>
        </Card>
      )}

      <section className="pf-card" aria-label={TITLES.methods[0]}>
        <div className="pf-card-h">
          <div>
            <h2>{TITLES.methods[0]}</h2>
            <p className="pf-card-sub">{TITLES.methods[1]}</p>
          </div>
          <button type="button" className="pf-toggle" aria-expanded={open} aria-controls="pf-methods" onClick={() => setOpen((v) => !v)}>
            {open ? '접기' : '자세히 보기'} <span aria-hidden="true">{open ? '▴' : '▾'}</span>
          </button>
        </div>
        {open && (
          <div id="pf-methods">
            <Legend a={selName} b={cmp && cmpName} />
            {METHOD_SUBS.map(([name, sub], i) => {
              const pair = sel.pairs[METHODS[i]]
              return (
                <div key={name} className="pf-m-row">
                  <div className="pf-m-name">
                    <b>{name}</b>
                    <Info>{`${terms.eval_cases[METHODS[i]]}${pair ? ` · ${METHOD_SUBS[base][0]} 대비 ${selName}에서 새로 맞힘 ${pair.new_right}개, 새로 틀림 ${pair.new_wrong}개` : ''}`}</Info>
                    <span className="pf-m-sub">{sub}</span>
                  </div>
                  <div className="pf-m-bars" role="img" aria-label={`${name.split(' ·')[0]} Top-1 정답률. ${sets.map(([n, p]) => `${n} ${pct(p.methods[i])}`).join(', ')}`}>
                    {sets.map(([, p, k]) => (
                      <p key={k} className={`pf-m-bar pf-${k}`}><i style={{ width: `${p.methods[i] * 100}%` }} /><span className="num">{pct(p.methods[i])}</span></p>
                    ))}
                  </div>
                </div>
              )
            })}
            <p className="pf-note">{METHODS_NOTE}</p>
            <div className="pf-dropped">
              <b>써 보고 빼기로 한 방법</b>
              {DROPPED.map((t) => <p key={t}>· {t}</p>)}
            </div>
          </div>
        )}
      </section>

      <div className="pf-two">
        <Card title={TITLES.unknown[0]}><ul className="pf-list">{UNKNOWN.map((t) => <li key={t}>{t}</li>)}</ul></Card>
        <Card title={TITLES.next[0]}><ul className="pf-list">{NEXT.map((t) => <li key={t}>{t}</li>)}</ul></Card>
      </div>
    </>
  )
}

export default EvalDashboard
