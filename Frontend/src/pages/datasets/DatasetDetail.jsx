import { useEffect, useRef, useState } from 'react'
import { getDataset } from '@/api/datasets'
import DataQuality from './DataQuality'
import { dash, orgYearVersion } from './format'

// S4 상세 슬라이드 패널 (A06). 열릴 때와 다른 데이터셋으로 바뀔 때 패널로 포커스, Esc 로 닫기
const DatasetDetail = ({ id, onSelect, onClose }) => {
  const [result, setResult] = useState({ id: null })
  const panelRef = useRef(null)

  useEffect(() => {
    let ignore = false
    getDataset(id)
      .then((data) => !ignore && setResult({ id, data }))
      .catch((error) => !ignore && setResult({ id, error }))
    return () => { ignore = true }
  }, [id])

  useEffect(() => { panelRef.current.focus() }, [id])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const d = result.id === id ? result.data : null
  return (
    <aside className="panel" ref={panelRef} tabIndex={-1} role="dialog" aria-labelledby="detail-title">
      <div className="panel-head">
        <div>
          <h2 id="detail-title">{d ? d.name : '데이터셋 상세'}</h2>
          {d && <span className="sub">{dash(d.name_en)}</span>}
        </div>
        <button type="button" className="text-btn" onClick={onClose}>닫기</button>
      </div>
      <div className="panel-body">
        {result.id !== id ? (
          <p className="note">불러오는 중</p>
        ) : result.error ? (
          <p className="err">오류 {dash(result.error.status)}: {result.error.detail}</p>
        ) : (
          <>
            <dl className="kv">
              <dt>분류</dt><dd>{dash(d.category)}</dd>
              <dt>개발기관</dt><dd>{dash(d.org)}</dd>
              <dt>버전</dt><dd>{d.version == null ? '—' : `v${d.version}`}</dd>
              <dt>데이터 종류</dt><dd>{dash(d.data_type)}</dd>
              <dt>기준흐름 단위</dt><dd>{dash(d.reference_unit)}</dd>
              <dt>같은 이름</dt><dd>{d.duplicate_count == null ? '—' : `${d.duplicate_count}건`}</dd>
              <dt>목록 행</dt><dd>{d.list_row == null ? '—' : `행 ${d.list_row}`} · {d.has_xml ? 'XML 연결됨' : '엑셀'}</dd>
            </dl>
            <DataQuality d={d} />
            {d.duplicates?.length > 0 && (
              <div>
                <h3 className="lb">같은 이름의 다른 데이터셋</h3>
                <ul className="dups">
                  {d.duplicates.map((x) => (
                    <li key={x.dataset_id}>
                      <button type="button" className="text-btn" onClick={() => onSelect(x.dataset_id)}>{orgYearVersion(x)}</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  )
}

export default DatasetDetail
