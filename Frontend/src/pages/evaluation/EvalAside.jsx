import terms from '@/terms'

// 탭 1(내가 올린 BOM)용 용어: terms.js 가 원천. 항목 이름은 화면 제목과 같다
const MINE = [
  [terms.no_ground_truth.label, terms.no_ground_truth.info],
  [terms.approve_match.label, terms.approve_match.info],
  [terms.human_work.label, terms.human_work.info],
  [`${terms.confidence.label} 등급`, terms.confidence.info],
]

// 탭 2·3용
const EVAL = [
  [terms.eval_tabs[1].label, 'AI가 만든 가상 부품 목록 2000개. 규칙을 모두 정한 뒤 한 번만 측정했습니다. 같은 재료가 여러 행에 나옵니다.'],
  [terms.eval_tabs[2].label, '논문·EPD·보고서에 실제로 적힌 소재·공정 이름. 표기가 제각각이라 더 어렵습니다.'],
  [terms.top1_rate.label, terms.top1_rate.info],
  [`${terms.top3_rate.label} · ${terms.recall_k.label}`, terms.top3_rate.info],
  [`${terms.confidence.label} 등급`, terms.confidence.info],
  [terms.ci95.label, terms.ci95.info],
]

const Glossary = ({ items }) => (
  <dl>
    {items.map(([name, text]) => (
      <div key={name}>
        <dt>{name}</dt>
        <dd>{text}</dd>
      </div>
    ))}
  </dl>
)

// "이 화면 읽는 법". 탭에 따라 문구가 바뀐다. 1024px 이상은 오른쪽에 따라오는 패널, 그보다 좁으면 본문 위 접힘 "용어 설명" (둘 중 하나만 보인다)
const EvalAside = ({ tab }) => {
  const items = tab === 'mine' ? MINE : EVAL
  return (
    <>
      <aside className="pf-aside" aria-labelledby="pf-aside-h">
        <h2 id="pf-aside-h">이 화면 읽는 법</h2>
        <Glossary items={items} />
      </aside>
      <details className="pf-aside-m">
        <summary>용어 설명</summary>
        <Glossary items={items} />
      </details>
    </>
  )
}

export default EvalAside
