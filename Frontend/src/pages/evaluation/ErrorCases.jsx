import { useEffect, useState } from 'react'
import { getDataset } from '@/api/datasets'
import terms from '@/terms'

const MAX_ROWS = 10

// 오답 사례: 입력 → 정답 → 시스템 1순위 → 이유. 정답·1순위는 데이터셋 이름(A06)으로 보이고, 조회 전·실패 시 id
const ErrorCases = ({ errors }) => {
  const shown = errors.slice(0, MAX_ROWS)
  const [names, setNames] = useState({}) // dataset_id → 이름

  useEffect(() => {
    let ignore = false
    const ids = new Set(shown.flatMap((e) => [...e.gold_ids, e.top1]).filter(Boolean))
    ids.forEach((id) => {
      getDataset(id)
        .then((d) => !ignore && setNames((n) => ({ ...n, [id]: d.name })))
        .catch(() => {}) // 실패하면 id 그대로
    })
    return () => { ignore = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 기록이 바뀔 때만 다시 조회한다
  }, [errors])

  const nameOf = (id) => names[id] ?? id

  return (
    <section className="sec" aria-label="오답 사례">
      <h3>오답 사례</h3>
      {errors.length === 0 ? (
        <p>이 기록에는 오답 사례가 없습니다.</p>
      ) : (
        <>
          {errors.length > MAX_ROWS && <p className="note">전체 {errors.length}건 중 {MAX_ROWS}건</p>}
          <div className="ev-scroll">
            <table className="ev-tbl">
              <thead>
                <tr><th>입력</th><th>정답</th><th>시스템 1순위</th><th>이유</th></tr>
              </thead>
              <tbody>
                {shown.map((e) => (
                  <tr key={e.id}>
                    <td>{e.query}</td>
                    <td>{e.gold_ids.length === 0 ? terms.no_answer.label : e.gold_ids.map(nameOf).join(', ')}</td>
                    <td>{e.top1 == null ? `후보 없음: 시스템이 ${terms.no_match.label}으로 처리` : nameOf(e.top1)}</td>
                    <td>{e.reason ?? '분석 전: 이 사례의 원인은 아직 기록하지 않았습니다'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}

export default ErrorCases
