import pool from './data/datasets.mock-pool.json'
import datasetDetail from './data/dataset.detail.json'

const SORTS = {
  relevance: null, // shortcut: 관련도는 풀 순서. 점수 계산은 백엔드에서
  year_desc: (a, b) => (b.year ?? -Infinity) - (a.year ?? -Infinity),
  name: (a, b) => a.name.localeCompare(b.name, 'ko'),
}

// 데이터 품질 필드는 상세(A06)에서만 준다 (명세 Dataset 표). 풀에는 두 응답이 같이 쓰도록 들어 있다
const DETAIL_ONLY = ['geography', 'allocation', 'cutoff', 'tech_summary']
const toListItem = (d) => Object.fromEntries(Object.entries(d).filter(([k]) => !DETAIL_ONLY.includes(k)))

// A05 GET /api/datasets
export const searchDatasets = (params = {}) => {
  const q = String(params.q ?? '').trim().toLowerCase()
  const categories = String(params.category ?? '').split(',').filter(Boolean)
  const group = String(params.group_duplicates ?? 'true') !== 'false'
  const limit = Math.min(Math.max(Number(params.limit) || 20, 1), 50)
  const offset = Math.max(Number(params.offset) || 0, 0)

  let items = pool.items.filter((d) => !q || d.name.toLowerCase().includes(q) || d.name_en?.toLowerCase().includes(q))
  if (group) {
    // 같은 한글명 중 최신 연도 하나만 남긴다 (연도가 같으면 풀에서 먼저 나온 것)
    const latest = new Map()
    for (const d of items) {
      const best = latest.get(d.name)
      if (!best || (d.year ?? -Infinity) > (best.year ?? -Infinity)) latest.set(d.name, d)
    }
    items = items.filter((d) => latest.get(d.name) === d)
  }

  // facets는 q 조건만 적용한 개수 (07-API명세서 A05)
  const facets = { category: {}, has_xml: { true: 0, false: 0 } }
  for (const d of items) {
    facets.category[d.category] = (facets.category[d.category] ?? 0) + 1
    facets.has_xml[String(d.has_xml)] += 1
  }

  if (categories.length) items = items.filter((d) => categories.includes(d.category))
  if (['true', 'false'].includes(String(params.has_xml))) items = items.filter((d) => String(d.has_xml) === String(params.has_xml))
  const compare = SORTS[params.sort] ?? null
  if (compare) items = [...items].sort(compare)

  return [200, { items: items.slice(offset, offset + limit).map(toListItem), total: items.length, facets }]
}

// A06 GET /api/datasets/{dataset_id}
export const getDataset = (id) => {
  if (id === datasetDetail.dataset_id) return [200, datasetDetail]
  const d = pool.items.find((x) => x.dataset_id === id)
  if (!d) return [404, { detail: `데이터셋을 찾을 수 없습니다: ${id}` }]
  // 상세 전용 필드는 XML에서 나오므로 풀에 값이 있는 것(데이터 품질 4개)만 쓰고 나머지는 지어내지 않고 null
  const duplicates = pool.items
    .filter((x) => x.name === d.name && x !== d)
    .map(({ dataset_id, org, year, version }) => ({ dataset_id, org, year, version }))
  return [200, { ...d, data_type: null, duplicates }]
}
