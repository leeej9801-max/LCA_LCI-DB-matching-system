import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router'
import DatasetBrowser from './datasets/DatasetBrowser'
import DatasetDetail from './datasets/DatasetDetail'

// S4 데이터셋 탐색 (FR-802). 검색 조건과 선택(id)은 URL 쿼리에 둔다 (새로고침·뒤로가기 유지)
const DatasetsPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedId = searchParams.get('id')
  const { id: _id, ...params } = Object.fromEntries(searchParams) // 목록 요청에는 상세 선택(id)을 넣지 않는다

  // 빈 값은 쿼리에서 지운다. 조건을 바꾸면 첫 페이지로 돌아간다
  const update = (changes, options) => {
    const next = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    if (!('offset' in changes) && !('id' in changes)) next.delete('offset')
    setSearchParams(next, options)
  }

  // 패널을 닫으면 패널을 열었던 행으로 포커스를 돌려준다
  const openedFrom = useRef(null)
  useEffect(() => {
    if (selectedId) {
      openedFrom.current ??= selectedId
      return
    }
    if (openedFrom.current) document.querySelector(`tr[data-id="${CSS.escape(openedFrom.current)}"]`)?.focus()
    openedFrom.current = null
  }, [selectedId])

  return (
    <>
      <div className="head">
        <h1>데이터셋 탐색</h1>
        <p>국가 LCI DB 698건. 이름·분류로 검색.</p>
      </div>

      <DatasetBrowser params={params} setParams={update} selectedId={selectedId} onRowClick={(id) => update({ id })} />

      {selectedId && <DatasetDetail id={selectedId} onSelect={(id) => update({ id })} onClose={() => update({ id: '' })} />}

      <details className="devinfo">
        <summary>개발 정보</summary>
        <p className="note">S4 · FR-802 · MVP</p>
        <table className="api">
          <tbody>
            <tr><td className="i">A05</td><td className="m">GET</td><td>{'/api/datasets?q=&category=&has_xml=&sort=&limit=&offset='}</td></tr>
            <tr><td className="i">A06<b>+</b></td><td className="m">GET</td><td>{'/api/datasets/{dataset_id}'}</td></tr>
          </tbody>
        </table>
      </details>
    </>
  )
}

export default DatasetsPage
