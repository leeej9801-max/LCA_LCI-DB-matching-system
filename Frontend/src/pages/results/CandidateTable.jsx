import ConfBar from '@/components/ConfBar'
import Info from '@/components/Info'
import { rateAltText, rateBasis, rateText } from '@/data/confidenceRates'
import terms, { plainText, roleLabel, sameName } from '@/terms'
import { shortOrg } from './format'

// 후보 1~3순위 비교 표 (U7 2-3). 열 = 후보, 행 = 속성. 열을 누르면(Enter·Space 포함) 그 후보를 현재 선택으로 고른다.
// 열마다 같은 항목이 같은 높이에 오도록 subgrid 로 행을 맞춘다 (칸 9개 = 머리 1 + 항목 8 — lcim.css `.cmp-col`의 span 9와 같아야 한다)
const ROWS = ['데이터셋', '종류', '기관·연도', terms.reference_flow.label, '보유 형태', terms.confidence.label, '근거', '같은 이름']

const CandidateTable = ({ cands, selectedId, busy, onPick }) => (
  <>
    <div className="cmp-grid" role="radiogroup" aria-label="후보 비교" style={{ '--n': cands.length }}>
      <div className="cmp-col cmp-labels" aria-hidden="true">
        <div className="cmp-h" />
        {ROWS.map((r) => <div className="cmp-c lbl" key={r}>{r}</div>)}
      </div>
      {cands.map((c, i) => {
        const on = c.dataset_id === selectedId
        const latest = c.reasons.some((r) => /중 최신/.test(r))
        return (
          <div
            key={c.dataset_id}
            className={['cmp-col', 'pick', on && 'sel', c.veto && 'veto'].filter(Boolean).join(' ')}
            role="radio" aria-checked={on} aria-disabled={busy} tabIndex={0}
            onClick={() => !busy && !on && onPick(c)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter' && e.key !== ' ') return
              e.preventDefault()
              if (!busy && !on) onPick(c)
            }}
          >
            <div className="cmp-h"><span className="radio" aria-hidden="true" />{i + 1}순위{c.veto && ' · 차단'}<span className="tag">{on ? '선택됨' : ''}</span></div>
            <div className="cmp-c"><b>{c.name}</b><span className="sub">{c.name_en}</span></div>
            <div className="cmp-c"><span className="visually-hidden">종류: </span>{c.role ? roleLabel(c.role) : '—'}</div>
            <div className="cmp-c"><span className="visually-hidden">기관·연도: </span>{shortOrg(c.org)} · {c.year ?? '—'}</div>
            <div className="cmp-c"><span className="visually-hidden">기준 단위: </span>{c.reference_unit ?? terms.no_reference_unit.label}</div>
            <div className="cmp-c"><span className="visually-hidden">보유 형태: </span>{c.has_xml ? 'XML' : terms.has_xml.excel}</div>
            <div className="cmp-c">
              <span className="visually-hidden">신뢰도: </span>
              <ConfBar level={c.confidence} />
              <span className="sub">같은 등급 정답률 {rateText(c.confidence)}</span>
            </div>
            <div className="cmp-c">
              <span className="visually-hidden">근거: </span>
              {c.veto && <b className="veto-text">차단 {c.veto.rule_id}: {c.veto.reason}</b>}
              {c.reasons.length ? plainText(c.reasons.join(' · ')) : !c.veto && '—'}
            </div>
            <div className="cmp-c">
              <span className="visually-hidden">같은 이름: </span>
              {c.duplicate_group ? `${sameName(c.duplicate_group.size)}${latest ? ` · ${terms.duplicate_group.latest}` : ''}` : '—'}
            </div>
          </div>
        )
      })}
    </div>
    <p className="rate-basis">같은 등급 정답률의 기준: {rateBasis()}<Info>{rateAltText()}</Info></p>
  </>
)

export default CandidateTable
