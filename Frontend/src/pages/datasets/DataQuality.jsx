import Info from '@/components/Info'
import terms from '@/terms'
import { carbonUnit, qualityRows, sig3 } from './format'

// 배출계수 한 줄 (X1): 값이 있으면 "0.984 kg CO₂e/kg (기후변화, 참고용)" + ⓘ(화석·생물기원·토지이용), 없으면 이유. 없는 값을 다른 데이터셋 값이나 0으로 채우지 않는다
const EmissionFactor = ({ carbon }) => (
  <div className="kv-line">
    <span className="k">{terms.emission_factor.label}<Info term="emission_factor" /></span>
    {carbon ? (
      <span className="v">
        {sig3(carbon.total)} {carbonUnit(carbon)} (기후변화, 참고용)
        <Info>
          {[['화석', carbon.fossil], ['생물기원', carbon.biogenic], ['토지이용', carbon.land_use]]
            .map(([name, v]) => `${name} ${v == null ? '—' : sig3(v)}`).join(' · ')} ({carbonUnit(carbon)}). 방법: {carbon.method}
        </Info>
      </span>
    ) : (
      <span className="v dim">없음 — 이 데이터셋에는 영향평가 결과가 없습니다</span>
    )}
  </div>
)

// S3 후보 비교와 S4 상세가 같이 쓴다
const DataQuality = ({ d }) => (
  <div className="dq">
    {qualityRows(d).map(([k, v]) => (
      <div className="kv-line" key={k}><span className="k">{k}</span><span className={k === '그 밖의 항목' ? 'v dim' : 'v'}>{v}</span></div>
    ))}
    <EmissionFactor carbon={d.carbon} />
  </div>
)

export default DataQuality
