import Info from '@/components/Info'
import terms from '@/terms'
import ErrorCases from './ErrorCases'

const GOLD_MIN = 150 // decisions "정답셋 로드맵"

const pct = (v) => `${Math.round(v * 1000) / 10}%`
const orDash = (v) => (v == null ? '—' : pct(v))
const measured = (s) => s.state === 'measured' && s.top1 != null

// 지표 이름·정의는 terms.js. 높은 신뢰도 오답률은 용어표에 없어 정의를 여기에 둔다
const METRICS = [
  ['top1', terms.top1.label, terms.top1.info],
  ['top3', terms.top3.label, terms.top3.info],
  ['high_conf_error_rate', '높은 신뢰도 오답률', '신뢰도 "높음"으로 낸 후보 중 틀린 비율'],
  ['abstain_reject_rate', terms.abstain_reject_rate.label, terms.abstain_reject_rate.info],
]

// 평가 한 건의 결과(A14): 결론 → 경고 → 측정 조건 → 단계별 기여 → 지표 정의 → 오답 사례.
// example(예시 데이터)이면 결론을 큰 헤드라인이 아니라 줄글 한 문장으로 쓴다 (ux-revision-2 R4)
const RunResult = ({ run, example }) => {
  const { gold_stats: gold, meta, metrics, ablation, errors } = run
  const base = ablation.find(measured)
  const top1 = metrics.top1 != null
  const gain = top1 && base && base.top1 !== metrics.top1
    ? ` · ${terms.baseline.label}보다 ${metrics.top1 > base.top1 ? '+' : ''}${Math.round((metrics.top1 - base.top1) * 1000) / 10}%p`
    : ''
  const conclusion = !top1 ? <p className="ev-conclusion">아직 측정하지 않음</p> : example ? (
    <p>
      이 예시 기록의 {terms.top1.label}<Info term="top1" />은 {pct(metrics.top1)}입니다
      {gain && ` (${gain.slice(3)})`}. {terms.gold_set.label}<Info term="gold_set" /> {gold.total}행 기준입니다.
    </p>
  ) : (
    <p className="ev-conclusion">
      {terms.top1.label}<Info term="top1" /> 정확도 {pct(metrics.top1)}{gain} · {terms.gold_set.label}<Info term="gold_set" /> {gold.total}행
    </p>
  )

  const conditions = [
    meta.model != null && `모델 ${meta.model}`,
    meta.index_hash != null && `인덱스 ${meta.index_hash}`,
    meta.dict_version != null && `사전 ${meta.dict_version}`,
    meta.rules_version != null && `규칙 ${meta.rules_version}`,
    meta.seed != null && `seed ${meta.seed}`,
    meta.elapsed_s != null && `${meta.elapsed_s}초`,
  ].filter(Boolean)

  return (
    <>
      {conclusion}
      {gold.total < GOLD_MIN && (
        <p>{terms.gold_set.label}{!top1 && <Info term="gold_set" />}이 {gold.total}행(정답 있음 {gold.answerable}, 정답 없음 {gold.no_answer})뿐이라 참고용입니다. {GOLD_MIN}행 이상으로 늘린 뒤 근거로 씁니다.</p>
      )}
      {conditions.length > 0 && <p className="note">{conditions.join(' · ')}</p>}

      <section className="sec" aria-label="단계별 기여">
        <h3>{terms.ablation.label}<Info term="ablation" /></h3>
        <ul className="ev-bars">
          {ablation.map((s) => (
            <li key={s.step} className="ev-bar">
              <span className="ev-step">{s.step}</span>
              {measured(s) ? (
                <>
                  <span className="ev-track"><span className="ev-fill" style={{ width: `${s.top1 * 100}%` }} /></span>
                  <span className="ev-val num">{pct(s.top1)}</span>
                </>
              ) : (
                <span className="ev-none">미측정</span>
              )}
            </li>
          ))}
        </ul>
        <div className="ev-scale" aria-hidden="true"><span>0%</span><span>50%</span><span>100%</span></div>

        <div className="ev-scroll">
          <table className="ev-tbl">
            <thead>
              <tr>
                <th>단계</th><th>{terms.top1.label}{!top1 && <Info term="top1" />}</th><th>{terms.top3.label}<Info term="top3" /></th>
                <th>{terms.abstain_reject_rate.label}<Info term="abstain_reject_rate" /></th><th>상태</th>
              </tr>
            </thead>
            <tbody>
              {ablation.map((s) => (
                <tr key={s.step}>
                  <td>{s.step}</td>
                  <td className="num">{orDash(s.top1)}</td>
                  <td className="num">{orDash(s.top3)}</td>
                  <td className="num">{orDash(s.abstain_reject_rate)}</td>
                  <td>{s.state === 'measured' ? '측정됨' : '미측정'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="sec" aria-label="지표 정의">
        <h3>지표 정의</h3>
        <dl className="ev-defs">
          {METRICS.map(([key, name, def]) => (
            <div key={key}>
              <dt>{name} <span className="num">{orDash(metrics[key])}</span></dt>
              <dd>{def}</dd>
            </div>
          ))}
        </dl>
      </section>

      <ErrorCases errors={errors} />
    </>
  )
}

export default RunResult
