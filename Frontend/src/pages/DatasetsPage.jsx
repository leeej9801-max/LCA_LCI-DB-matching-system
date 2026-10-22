import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { searchDatasets } from '@/api/datasets'
import DevInfo from '@/components/DevInfo'
import MockNotice from '@/components/MockNotice'
import DatasetBrowser from './datasets/DatasetBrowser'
import DatasetDetail from './datasets/DatasetDetail'

// S4 데이터셋 탐색 (FR-802). 검색 조건과 선택(id)은 URL 쿼리에 둔다 (새로고침·뒤로가기 유지)
const DatasetsPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const [allCount, setAllCount] = useState(null) // 국가 LCI DB 전체 건수(같은 이름 포함). 못 가져오면 건수는 쓰지 않는다
  const selectedId = searchParams.get('id')
  const { id: _id, ...params } = Object.fromEntries(searchParams) // 목록 요청에는 상세 선택(id)을 넣지 않는다

  useEffect(() => {
    let ignore = false
    searchDatasets({ limit: 1, group_duplicates: 'false' }).then((d) => !ignore && setAllCount(d.total)).catch(() => {})
    return () => { ignore = true }
  }, [])

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
    <div className="u7">
      <div className="u7-head">
        <div>
          <h1>국가 LCI DB</h1>
          <p className="meta lg">국가 LCI DB{allCount != null && ` ${allCount.toLocaleString()}건`} · 이름이나 분류로 찾아 내용을 확인합니다.</p>
        </div>
      </div>

      <MockNotice path="/datasets" />

      <div className={selectedId ? 'ds-layout open' : 'ds-layout'}>
        <div className="ds-main">
          <DatasetBrowser params={params} setParams={update} selectedId={selectedId} onRowClick={(id) => update({ id })} />
        </div>
        {selectedId && <DatasetDetail id={selectedId} onSelect={(id) => update({ id })} onClose={() => update({ id: '' })} />}
      </div>

      <DevInfo>
        <p className="note">S4 · FR-802 · MVP</p>
        <p className="note">실제 연결됨(A05·A06): <code>npm run dev:real</code> 에서 이 두 API만 백엔드로 보낸다</p>
        <table className="api">
          <tbody>
            <tr><td className="i">A05</td><td className="m">GET</td><td>{'/api/datasets?q=&category=&has_xml=&sort=&limit=&offset='}</td></tr>
            <tr><td className="i">A06<b>+</b></td><td className="m">GET</td><td>{'/api/datasets/{dataset_id}'}</td></tr>
          </tbody>
        </table>
      </DevInfo>
    </div>
  )
}

export default DatasetsPage
