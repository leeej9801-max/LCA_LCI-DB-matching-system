import { useState } from 'react'
import DatasetBrowser from './DatasetBrowser'

// S3 직접 선택: S4의 검색·필터·표를 그대로 쓰고, 조건은 URL 대신 내부 상태에 둔다. 행마다 "이 행에 지정"
// initialQuery: 처음 검색어(행의 normalized_name). 피커를 열 때마다 새로 시작한다
const DatasetPicker = ({ initialQuery, busy, onPick, onClose }) => {
  const [params, setParams] = useState(initialQuery ? { q: initialQuery } : {})

  // 빈 값은 지운다. 조건을 바꾸면 첫 페이지로 돌아간다
  const update = (changes) =>
    setParams((p) => {
      const next = { ...p }
      for (const [k, v] of Object.entries(changes)) {
        if (v) next[k] = v
        else delete next[k]
      }
      if (!('offset' in changes)) delete next.offset
      return next
    })

  return (
    <div className="picker">
      <div className="picker-head">
        <h3>직접 선택</h3>
        <button type="button" className="text-btn" onClick={onClose}>닫기</button>
      </div>
      <DatasetBrowser
        params={params}
        setParams={update}
        rowAction={(d) => <button type="button" className="btn sm" disabled={busy} onClick={() => onPick(d)}>이 행에 지정</button>}
      />
    </div>
  )
}

export default DatasetPicker
