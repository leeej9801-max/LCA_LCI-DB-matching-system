import ErrorCases from './ErrorCases'

const GOLD_MIN = 150 // decisions "정답셋 로드맵"

const pct = (v) => `${Math.round(v * 1000) / 10}%`
const orDash = (v) => (v == null ? '—' : pct(v))
const measured = (s) => s.state === 'measured' && s.top1 != null

const METRICS = [
  ['top1', 'Top-1', '정답이 있는 질의 중 시스템 1순위가 정답인 비율'],
  ['top3', 'Top-3', '정답이 있는 질의 중 상위 3개 안에 정답이 있는 비율'],
  ['high_conf_error_rate', '높은 신뢰도 오답률', '신뢰도 "높음"으로 낸 후보 중 틀린 비율'],
  ['abstain_reject_rate', '정답 없음 거부율', '정답이 목록에 없는 질의에서 후보를 내지 않고 "정답 없음"으로 처리한 비율'],
]

// 평가 한 건의 결과(A14): 결론 → 경고 → 측정 조건 → 단계별 기여 → 지표 정의 → 오답 사례
const RunResult = ({ run }) => {
  const { gold_stats: gold, meta, metrics, ablation, errors } = run
  const base = ablation.find(measured)
  const conclusion = metrics.top1 == null
    ? '아직 측정하지 않음'
    : `Top-1 정확도 ${pct(metrics.top1)}${base && base.top1 !== metrics.top1 ? ` · 기준선(TF-IDF)보다 ${metrics.top1 > base.top1 ? '+' : ''}${Math.round((metrics.top1 - base.top1) * 1000) / 10}%p` : ''} · 정답셋 ${gold.total}행`

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
      <p className="ev-conclusion">{conclusion}</p>
      {gold.total < GOLD_MIN && (
        <p>정답셋이 {gold.total}행(정답 있음 {gold.answerable}, 정답 없음 {gold.no_answer})뿐이라 참고용입니다. {GOLD_MIN}행 이상으로 늘린 뒤 근거로 씁니다.</p>
      )}
      {conditions.length > 0 && <p className="note">{conditions.join(' · ')}</p>}

      <section className="sec" aria-label="단계별 기여">
        <h3>단계별 기여</h3>
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
              <tr><th>단계</th><th>Top-1</th><th>Top-3</th><th>정답 없음 거부율</th><th>상태</th></tr>
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
