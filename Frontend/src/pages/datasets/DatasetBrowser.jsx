import { useEffect, useRef, useState } from 'react'
import { searchDatasets } from '@/api/datasets'
import terms, { sameName } from '@/terms'
import { dash, serverHint, shortOrg } from './format'

const PAGE_SIZE = 20
const SORTS = [['relevance', '관련도'], ['year_desc', '연도 최신순'], ['name', '이름순']]
const HAS_XML = [['', '전체'], ['true', terms.has_xml.xml], ['false', terms.has_xml.excel]]

// 분류 고르기: 여러 개를 고를 수 있는 작은 메뉴(드롭다운). 바깥을 누르거나 Esc 로 닫는다
const CategoryMenu = ({ selected, counts, onToggle }) => {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)
  const btn = useRef(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e) => !wrap.current.contains(e.target) && setOpen(false)
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      btn.current.focus()
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  const text = selected.length === 0 ? '전체' : selected.length === 1 ? selected[0] : `${selected[0]} 외 ${selected.length - 1}`
  return (
    <span className="dd-wrap" ref={wrap}>
      <button ref={btn} type="button" className="select-btn" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        분류: {text} <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <fieldset className="dd-menu checks">
          <legend className="visually-hidden">분류</legend>
          {Object.entries(counts).map(([c, n]) => (
            <label key={c}><input type="checkbox" checked={selected.includes(c)} onChange={() => onToggle(c)} /> {c} <span className="num">{n}</span></label>
          ))}
        </fieldset>
      )}
    </span>
  )
}

// S4의 검색·필터·표·페이지 (A05). 검색 조건은 params(문자열 값 객체)로 받고 바꿀 때 setParams(changes, options)를 부른다.
// S4 화면은 URL 쿼리로, S3 직접 선택 피커는 내부 상태로 조건을 들고 있다.
// onRowClick(id): 행 선택(S4 상세) · rowAction(dataset): 행 끝 동작 버튼(피커의 "이 행에 지정")
// 데이터셋 "종류"(소재·공정 …)는 A05 응답에 없어 열과 드롭다운을 두지 않는다(U7 요청서 참고)
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
  const categoryCounts = { ...Object.fromEntries(categories.map((c) => [c, 0])), ...data?.facets.category }
  const grouped = params.group_duplicates !== 'false'

  return (
    <div className="u7-card ds-card">
      <div className="ds-controls">
        <form
          className="search-box grow"
          role="search"
          onSubmit={(e) => {
            e.preventDefault()
            setParams({ q: e.currentTarget.elements.q.value.trim() })
          }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          {/* key: 뒤로가기로 q가 바뀌면 입력칸도 맞춘다. Enter 로 검색 */}
          <input name="q" aria-label="검색어 (한글·영문·약어)" placeholder="한글·영문·약어로 검색" key={q} defaultValue={q} maxLength={100} />
        </form>
        <fieldset className="seg2">
          <legend className="visually-hidden">보유 형태</legend>
          {HAS_XML.map(([v, label]) => (
            <label key={v || 'all'}>
              <input type="radio" name="has_xml" value={v} checked={hasXml === v} onChange={() => setParams({ has_xml: v })} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <CategoryMenu selected={categories} counts={categoryCounts} onToggle={toggleCategory} />
        <select className="select-btn" aria-label="정렬" value={sort} onChange={(e) => setParams({ sort: e.target.value === 'relevance' ? '' : e.target.value })}>
          {SORTS.map(([v, label]) => <option key={v} value={v}>정렬: {label}</option>)}
        </select>
      </div>

      <div className="ds-count" aria-live="polite">
        <span>{loading ? '불러오는 중' : result.error ? '' : <><b>{q ? `"${q}" ` : ''}{total}건</b>{grouped && ' · 같은 이름은 최신판만 표시'}</>}</span>
        <label className="switch">
          <input type="checkbox" role="switch" checked={!grouped} onChange={(e) => setParams({ group_duplicates: e.target.checked ? 'false' : '' })} />
          <span className="knob" aria-hidden="true" />같은 이름 모두 보기
        </label>
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
          <div className="tbl-scroll"><table className="u7-tbl ds">
            <colgroup><col /><col className="w-cat" /><col className="w-org" /><col className="w-year" /><col className="w-ver" /><col className="w-has" />{rowAction && <col className="w-act" />}</colgroup>
            <thead>
              <tr>
                <th>이름</th><th>분류</th><th>개발기관</th><th>연도</th><th>버전</th><th>보유</th>
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
                  <td className="c-in">
                    <span className="ell"><b>{d.name}</b>{d.duplicate_count > 1 && <span className="dup">{sameName(d.duplicate_count)}</span>}</span>
                    <span className="sub ell">{dash(d.name_en)}</span>
                  </td>
                  <td>{d.category}</td>
                  <td><span className="ell">{shortOrg(d.org)}</span></td>
                  <td className="num">{dash(d.year)}</td>
                  <td className="num">{d.version == null ? '—' : `v${d.version}`}</td>
                  <td className={d.has_xml ? undefined : 'dim'}>{d.has_xml ? 'XML' : terms.has_xml.excel}</td>
                  {rowAction && <td className="nowrap">{rowAction(d)}</td>}
                </tr>
              ))}
            </tbody>
          </table></div>
          <nav className="u7-pager" aria-label="페이지">
            <span className="num">{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} / {total}건</span>
            <span>
              <button type="button" className="text-btn" disabled={offset === 0} onClick={() => setParams({ offset: offset > PAGE_SIZE ? String(offset - PAGE_SIZE) : '' })}>‹ 이전</button>
              <span aria-hidden="true"> · </span>
              <button type="button" className="text-btn" disabled={offset + PAGE_SIZE >= total} onClick={() => setParams({ offset: String(offset + PAGE_SIZE) })}>다음 ›</button>
            </span>
          </nav>
        </>
      )}
    </div>
  )
}

export default DatasetBrowser
