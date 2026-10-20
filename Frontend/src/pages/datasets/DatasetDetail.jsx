import { useEffect, useRef, useState } from 'react'
import { getDataset } from '@/api/datasets'
import terms from '@/terms'
import DataQuality from './DataQuality'
import { dash, orgYearVersion, serverHint } from './format'

// 상세 패널에 나오는 값. 종류(소재·공정 …)와 합본 안내는 A06 응답에 종류가 없어 두지 않는다
const infoRows = (d) => [
  ['분류', dash(d.category)],
  ['개발기관', dash(d.org)],
  ['연도·버전', `${dash(d.year)}${d.version == null ? '' : ` · v${d.version}`}`],
  [terms.reference_flow.label, dash(d.reference_unit)],
  ['보유 형태', d.has_xml ? terms.has_xml.xml : terms.has_xml.excel],
]

// S4 상세 패널 (A06, 380px, 목록 오른쪽에 붙는다). 열릴 때와 다른 데이터셋으로 바뀔 때 패널로 포커스, Esc 로 닫기
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
    <aside className="ds-detail" ref={panelRef} tabIndex={-1} role="dialog" aria-labelledby="detail-title">
      <div className="ds-detail-head">
        <div>
          <h2 id="detail-title">{d ? d.name : '데이터셋 상세'}</h2>
          {d && <div className="sub">{dash(d.name_en)}</div>}
        </div>
        <button type="button" className="sq" title="닫기" aria-label="닫기" onClick={onClose}>✕</button>
      </div>
      <div className="ds-detail-body">
        {result.id !== id ? (
          <p className="note">불러오는 중</p>
        ) : result.error ? (
          <>
            <p className="err">오류 {dash(result.error.status)}: {result.error.detail}</p>
            {serverHint(result.error) && <p className="note">{serverHint(result.error)}</p>}
          </>
        ) : (
          <>
            <h3>기본 정보</h3>
            <dl className="kv-list">
              {infoRows(d).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
            </dl>
            <h3>{terms.data_quality.label}</h3>
            <DataQuality d={d} />
            {d.duplicates?.length > 0 && (
              <>
                <h3>같은 이름의 다른 데이터셋</h3>
                <ul className="dups">
                  {d.duplicates.map((x) => (
                    <li key={x.dataset_id}>
                      <button type="button" className="text-btn" onClick={() => onSelect(x.dataset_id)}>{orgYearVersion(x)}</button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>
    </aside>
  )
}

export default DatasetDetail
