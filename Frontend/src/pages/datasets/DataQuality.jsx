import { dash } from './format'

const OLD_YEARS = 10 // 경과 연수가 이 이상이면 "오래된 데이터" 글자를 붙인다 (색 경고 아님)

// 데이터 품질 묶음: 시간(기준연도·경과 연수)·지역·할당·컷오프·기술 요약. S3 후보 비교와 S4 상세가 같이 쓴다.
// 경과 연수는 표시용으로 오늘 날짜에서 센다. 값이 null이면 "—"
const DataQuality = ({ d }) => {
  const age = d.year == null ? null : new Date().getFullYear() - d.year
  return (
    <div className="dq">
      <span className="lb">
        데이터 품질
        <button type="button" className="hint" title="LCA에서 데이터를 고를 때 시간·지역·기술이 연구 대상과 맞는지 봅니다." aria-label="데이터 품질이란: LCA에서 데이터를 고를 때 시간·지역·기술이 연구 대상과 맞는지 봅니다.">?</button>
      </span>
      <ul className="plain">
        <li>
          기준연도 {dash(d.year)}{age != null && ` (${age <= 0 ? '올해' : `${age}년 전`})`}
          {age != null && age >= OLD_YEARS && ' · 오래된 데이터'}
        </li>
        <li>지역 {dash(d.geography)}</li>
        <li>할당 {dash(d.allocation)}</li>
        <li>컷오프 {dash(d.cutoff)}</li>
        <li>
          {d.tech_summary == null
            ? '기술 요약 —'
            : <details><summary>기술 요약</summary>{d.tech_summary}</details>}
        </li>
      </ul>
    </div>
  )
}

export default DataQuality
