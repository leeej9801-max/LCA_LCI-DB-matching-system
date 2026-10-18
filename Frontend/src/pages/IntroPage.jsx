import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { isMock } from '@/api/client'
import { searchDatasets } from '@/api/datasets'
import Info from '@/components/Info'
import terms from '@/terms'

const FLOW = [
  ['BOM', '자동차 부품 목록 파일을 올립니다'],
  ['정제', '품명·단위·수량을 같은 형식으로 맞춥니다'],
  ['후보 검색', '글자 일치와 의미 유사 두 방식을 합쳐 후보를 찾습니다'],
  ['사람이 확인·승인', '행마다 후보를 보고 확정합니다'],
  ['내보내기', '승인한 행만 파일로 받습니다'],
]

const LIMITS = [
  '인증용 제품탄소발자국이 아니라 스크리닝 수준 추정입니다.',
  '사용 단계는 다루지 않습니다.',
  '샘플 BOM은 공개 자료 기반의 가정이며 실제 업체 BOM이 아닙니다.',
  '후보는 사람이 승인해야 확정됩니다.',
]

// 소개 화면 (ux-revision-2 "소개 화면"). 짧고 사실만. 수치·절감 시간·성능 숫자는 쓰지 않는다
const IntroPage = () => {
  const navigate = useNavigate()
  const [stats, setStats] = useState(null) // { total, category } 실제 서버일 때만

  // 건수는 실제 서버일 때만. 오류가 나면 숫자 칸만 비운다
  useEffect(() => {
    if (isMock('/datasets')) return
    let ignore = false
    searchDatasets({ group_duplicates: 'false', limit: 1 })
      .then((d) => !ignore && setStats({ total: d.total, category: d.facets.category }))
      .catch(() => {})
    return () => { ignore = true }
  }, [])

  return (
    <>
      <div className="head">
        <h1>자동차 부품 BOM의 각 행에 맞는 국가 LCI 데이터셋 후보를 찾아 줍니다</h1>
        <p>사람이 확인·승인한 결과만 내보내는 도구입니다.</p>
      </div>
      <div className="flex-row">
        <button type="button" className="btn pri lg" onClick={() => navigate('/upload', { state: { sample: true } })}>샘플로 해 보기</button>
        <Link className="btn lg" to="/upload">BOM 올리기</Link>
      </div>

      <section className="sec" aria-label="왜 필요한가">
        <h2 className="intro-h">왜 필요한가</h2>
        <p>BOM의 행마다 맞는 {terms.lci_dataset.label}<Info term="lci_dataset" />를 사람이 찾는 일은 반복 작업이고, 같은 부품도 약어·영문·별칭으로 표기가 제각각이라 검색이 잘 맞지 않습니다.</p>
      </section>

      <section className="sec" aria-label="어떻게 동작하나">
        <h2 className="intro-h">어떻게 동작하나</h2>
        <ol className="flow">
          {FLOW.map(([title, text]) => <li key={title}><b>{title}</b><span className="sub">{text}</span></li>)}
        </ol>
      </section>

      <section className="sec" aria-label="쓰는 데이터">
        <h2 className="intro-h">쓰는 데이터</h2>
        <p>
          국가 LCI DB의 {terms.lci_dataset.label}입니다.
          {stats && <> 같은 이름을 모두 세어 {stats.total}건: {Object.entries(stats.category).map(([c, n]) => `${c} ${n}건`).join(' · ')}.</>}
        </p>
      </section>

      <section className="sec" aria-label="어떻게 검증했나">
        <h2 className="intro-h">어떻게 검증했나</h2>
        <p>정답셋을 만들어 방식을 하나씩 더하며 비교합니다. 측정 결과는 평가 화면에서 봅니다.</p>
        <div><Link className="btn" to="/evaluation">평가 화면 보기</Link></div>
      </section>

      <section className="sec" aria-label="하지 않는 것">
        <h2 className="intro-h">하지 않는 것</h2>
        <ul className="plain">{LIMITS.map((t) => <li key={t}>{t}</li>)}</ul>
      </section>

      <p className="note">PostgreSQL + pgvector, bge-m3 임베딩, TF-IDF + RRF, FastAPI, React로 만들었습니다.</p>
    </>
  )
}

export default IntroPage
