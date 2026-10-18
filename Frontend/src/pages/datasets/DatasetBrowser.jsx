import { useEffect, useState } from 'react'
import { searchDatasets } from '@/api/datasets'
import Info from '@/components/Info'
import terms, { sameName } from '@/terms'
import { dash, orgYearVersion, serverHint } from './format'

const PAGE_SIZE = 20
const SORTS = [['relevance', '관련도'], ['year_desc', '연도 최신순'], ['name', '이름순']]
const HAS_XML = [['', '전체'], ['true', terms.has_xml.xml], ['false', terms.has_xml.excel]]

// S4의 검색·필터·표·페이지 (A05). 검색 조건은 params(문자열 값 객체)로 받고 바꿀 때 setParams(changes, options)를 부른다.
// S4 화면은 URL 쿼리로, S3 직접 선택 피커는 내부 상태로 조건을 들고 있다.
// onRowClick(id): 행 선택(S4 상세) · rowAction(dataset): 행 끝 동작 버튼(피커의 "이 행에 지정")
const DatasetBrowser = ({ params, setParams, selectedId, onRowClick, rowAction }) => {
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState({ key: null })

  const q = params.q ?? ''
  const categories = params.category?.split(',').filter(Boolean) ?? []
  const hasXml = params.has_xml ?? '' // 'true' XML 보유만 · 'false' 엑셀만 · '' 전체
  const sort = params.sort ?? 'relevance'
  const offset = Math.max(Number(params.offset) || 0, 0)
  const query = JSON.stringify(params)
  const key = `${query}#${reload}`

  useEffect(() => {
    const requestKey = `${query}#${reload}`
    let ignore = false
    searchDatasets({ ...JSON.parse(query), limit: PAGE_SIZE })
      .then((data) => !ignore && setResult({ key: requestKey, data }))
      .catch((error) => !ignore && setResult({ key: requestKey, error }))
    return () => { ignore = true }
  }, [query, reload])

  const toggleCategory = (c) =>
    setParams({ category: (categories.includes(c) ? categories.filter((x) => x !== c) : [...categories, c]).join(',') })

  const loading = result.key !== key
  const data = result.data // 다시 불러오는 동안에도 이전 결과를 보여 준다
  const total = data?.total ?? 0
  // 마지막 페이지를 넘는 offset(URL 직접 입력 등)은 마지막 페이지로 맞춘다. 새 결과가 온 뒤에만 판단
  const lastOffset = total > 0 ? Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE : 0
  useEffect(() => {
    if (loading || !data || offset <= lastOffset) return
    setParams({ offset: lastOffset ? String(lastOffset) : '' }, { replace: true })
  }, [loading, data, offset, lastOffset, setParams])
  const firstDup = data?.items.find((d) => d.duplicate_count > 1)?.dataset_id // ⓘ 는 첫 행에만
  const categoryCounts = { ...Object.fromEntries(categories.map((c) => [c, 0])), ...data?.facets.category }

  return (
    <>
      <form
        className="search"
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          setParams({ q: e.currentTarget.elements.q.value.trim() })
        }}
      >
        <div className="search-row">
          {/* key: 뒤로가기로 q가 바뀌면 입력칸도 맞춘다 */}
          <input name="q" className="inp lg" aria-label="검색어 (한글·영문·약어)" placeholder="한글·영문·약어" key={q} defaultValue={q} maxLength={100} />
          <button type="submit" className="btn pri lg">검색</button>
        </div>
      </form>

      <div className="filters">
        <fieldset className="seg">
          <legend className="visually-hidden">보유 형태</legend>
          {HAS_XML.map(([v, label]) => (
            <label key={v || 'all'}>
              <input type="radio" name="has_xml" value={v} checked={hasXml === v} onChange={() => setParams({ has_xml: v })} />
              <span className="num">{label}{v && data && ` (${data.facets.has_xml[v]})`}</span>
            </label>
          ))}
        </fieldset>
        <Info term="has_xml" />
        <div className="toggles" role="group" aria-label="분류">
          {Object.entries(categoryCounts).map(([c, n]) => (
            <button key={c} type="button" className="toggle" aria-pressed={categories.includes(c)} onClick={() => toggleCategory(c)}>
              {c} <span className="num">{n}</span>
            </button>
          ))}
        </div>
        <select className="sort" aria-label="정렬" value={sort} onChange={(e) => setParams({ sort: e.target.value === 'relevance' ? '' : e.target.value })}>
          {SORTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
      </div>

      <div className="summary" aria-live="polite">
        {loading ? '불러오는 중' : result.error ? '' : (
          <>
            <b>{q ? `"${q}" ` : ''}{total}건</b>
            {params.group_duplicates !== 'false' && <span className="note">같은 이름은 최신 1건만 표시</span>}
            <label className="note">
              <input type="checkbox" checked={params.group_duplicates === 'false'} onChange={(e) => setParams({ group_duplicates: e.target.checked ? 'false' : '' })} />
              {' '}같은 이름 모두 보기
            </label>
          </>
        )}
      </div>

      {result.error && !loading ? (
        <div className="state">
          <p className="err">오류 {result.error.status ?? '—'}: {result.error.detail}</p>
          {serverHint(result.error) && <p className="note">{serverHint(result.error)}</p>}
          <button type="button" className="text-btn" onClick={() => setReload((n) => n + 1)}>다시 시도</button>
        </div>
      ) : data && total === 0 && !loading ? (
        <div className="state"><p>일치하는 데이터셋 없음.</p></div>
      ) : data && (
        <>
          <p className="note">{terms.has_xml.xml}는 투입·산출 상세로 계산할 수 있고, {terms.has_xml.excel}은 목록 정보만 있어 이후 계산에서 빠집니다.</p>
          <table className="tbl">
            <thead>
              <tr>
                <th>한글명</th><th>분류</th><th>개발기관 · 연도 · 버전</th><th>보유 형태</th>
                {rowAction && <th><span className="visually-hidden">선택</span></th>}
              </tr>
            </thead>
            <tbody>
              {data.items.map((d) => (
                <tr
                  key={d.dataset_id}
                  data-id={d.dataset_id}
                  className={d.dataset_id === selectedId ? 'sel' : undefined}
                  {...(onRowClick && {
                    tabIndex: 0,
                    'aria-selected': d.dataset_id === selectedId,
                    onClick: () => onRowClick(d.dataset_id),
                    onKeyDown: (e) => {
                      if (e.key !== 'Enter' && e.key !== ' ') return
                      e.preventDefault()
                      onRowClick(d.dataset_id)
                    },
                  })}
                >
                  <td>
                    <b>{d.name}</b>
                    {d.duplicate_count > 1 && (
                      <span className="dup">{sameName(d.duplicate_count)}{d.dataset_id === firstDup && <Info term="duplicate_group" />}</span>
                    )}
                    <span className="sub">{dash(d.name_en)}</span>
                  </td>
                  <td className="nowrap">{d.category}</td>
                  <td>{orgYearVersion(d)}</td>
                  <td className="nowrap">{d.has_xml ? <span className="fmt xml">● {terms.has_xml.xml}</span> : <span className="fmt xls">○ {terms.has_xml.excel}</span>}</td>
                  {rowAction && <td className="nowrap">{rowAction(d)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          <nav className="pager" aria-label="페이지">
            <button type="button" className="text-btn" disabled={offset === 0} onClick={() => setParams({ offset: offset > PAGE_SIZE ? String(offset - PAGE_SIZE) : '' })}>이전</button>
            <span aria-hidden="true">·</span>
            <span className="num">{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}</span>
            <span aria-hidden="true">·</span>
            <button type="button" className="text-btn" disabled={offset + PAGE_SIZE >= total} onClick={() => setParams({ offset: String(offset + PAGE_SIZE) })}>다음</button>
          </nav>
        </>
      )}
    </>
  )
}

export default DatasetBrowser
