import DataQuality from '../datasets/DataQuality'
import { orgYearVersion } from '../datasets/format'
import { confidenceText } from './format'

// 후보 1~3순위 나란히 비교. 열마다 같은 항목이 같은 높이에 오도록 subgrid로 행을 맞춘다 (열마다 칸 11개 — lcim.css `.cand`의 span 11과 같아야 한다)
// 현재 선택 열에는 승인 버튼을 두지 않는다. 승인은 아래 환산 상태의 `현재 선택 승인` 하나다
const CandidateGrid = ({ cands, selectedId, busy, confirmId, setConfirmId, onApprove }) => (
  <div className="cmp" style={{ '--n': cands.length }}>
    {cands.map((c, i) => (
      <section key={c.dataset_id} className={c.veto ? 'cand veto' : 'cand'} aria-label={`${i + 1}순위 후보`}>
        <div className="cell"><span className="lb">{i + 1}순위{c.veto && ' · 차단'}{c.dataset_id === selectedId && ' · 현재 선택'}</span><b>{c.name}</b><span className="sub">{c.name_en}</span></div>
        <div className="cell"><span className="lb">분류</span>{c.category}</div>
        <div className="cell"><span className="lb">기관 · 연도 · 버전</span>{orgYearVersion(c)}</div>
        <div className="cell"><span className="lb">기준 단위</span>{c.reference_unit}</div>
        <div className="cell"><span className="lb">보유 형태</span>{c.has_xml ? '● XML' : '○ 엑셀만'}</div>
        <div className="cell"><DataQuality d={c} /></div>
        <div className="cell"><span className="lb">신뢰도</span>{confidenceText(c)}</div>
        <div className="cell">
          <span className="lb">근거</span>
          {c.reasons.length ? <ul className="plain">{c.reasons.map((r) => <li key={r}>{r}</li>)}</ul> : '—'}
        </div>
        <div className="cell">
          {c.duplicate_group && <><span className="lb">동명 그룹</span>동명 {c.duplicate_group.size}건 중 하나</>}
        </div>
        <div className="cell veto-text">{c.veto && `차단 ${c.veto.rule_id}: ${c.veto.reason}`}</div>
        <div className="cell act">
          {c.dataset_id === selectedId ? null : c.veto ? (
            confirmId === c.dataset_id ? (
              <>
                <p className="note">차단 규칙을 무시합니다. 이력에 남습니다.</p>
                <div className="flex-row">
                  <button type="button" className="btn sm" disabled={busy} onClick={() => onApprove(c)}>확인</button>
                  <button type="button" className="text-btn" onClick={() => setConfirmId(null)}>취소</button>
                </div>
              </>
            ) : (
              <button type="button" className="btn sm" disabled={busy} onClick={() => setConfirmId(c.dataset_id)}>차단 무시하고 승인</button>
            )
          ) : (
            <button type="button" className="btn pri sm" disabled={busy} onClick={() => onApprove(c)}>이 후보로 승인</button>
          )}
        </div>
      </section>
    ))}
  </div>
)

export default CandidateGrid
