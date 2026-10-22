import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { getEvalRun, listEvalRuns } from '@/api/eval'
import Pictogram from '@/components/Pictogram'
import { pick } from '@/pages/evaluation/pick'
import '@styles/intro.css'

const MAX_ROWS = 2000 // Backend/app/bom/reader.py 의 MAX_ROWS(업로드 안내 "한 번에 2,000행까지"). 서버 제한값이지 성능 지표가 아니다

// 소개 화면의 문구는 모두 여기 한 곳에 둔다 (U12). 제목은 평가·업무 용어, 부제는 쉬운 말.
// 숫자는 측정한 값만, 데이터 이름과 함께 쓴다. 절감·시간 단축 값은 쓰지 않는다
const INTRO = {
  tag: 'LCA 목록분석(LCI) · 데이터셋 매칭',
  engine: ['의미 기반 검색', 'bge-m3 임베딩 모델'],
  h1: ['BOM', 'LCI DB 매칭 자동화'], // 가운데 ↔ 앞뒤에서만 줄이 바뀔 수 있다
  sub: '부품 한 줄마다 국가 LCI 데이터셋 후보를 찾고 단위까지 맞춥니다.',
  lead: '후보 탐색·단위 환산은 도구가, 최종 확정은 담당자가 합니다.',
  steps: [
    ['① 입력 정제', 'BOM 한 줄(예: SPCC 냉연강판 1.2T · 2.4 kg)의 품명·규격·단위를 정리'],
    ['② 사전 + 의미 검색', '약어·별칭은 사전으로 풀고, 이름이 달라도 뜻이 가까운 데이터셋을 찾음'],
    ['③ 단위 환산', 'kg → t는 자동, EA → kg는 개당 중량 입력 후'],
    ['④ 후보 비교', '상위 3건을 근거·신뢰도와 함께 나란히'],
    ['⑤ 승인·내보내기', '담당자가 확정한 행만 내보냄'],
  ],
  // 예시 그림 (U12b): 실제 앱 결과(가상 BOM 2000 평가 입력, dev:real)를 그대로 옮긴 것. 결과에 없는 값은 쓰지 않는다
  scene: {
    pill: '사전 + 의미 검색', approve: '담당자 확정', unit: ['단위 변환은 코드가', 'kg → t 자동 · EA → kg'],
    input: ['입력 행', '전원부 외함 커버', ' · SPCC t1.2×200×300', '0.57 kg'],
    head: ['후보 3건 · 1위 신뢰도 높음', '2·3위는 구분 확인용'],
    top: ['냉간압연강판', '글자·의미 1위 · 사전: SPCC → 냉간압연강판', '신뢰도 높음'],
    others: [['냉간압연강판(스테인리스)', '다른 소재'], ['열간압연강판', '앞 공정 단계']], // 이름 옆 "소재"는 두 후보의 데이터셋 종류(결과 화면의 종류 칸)
    note: '실제 앱 결과를 옮긴 예시입니다.',
  },
  facts: [['대상 사용자', 'LCA 실무자, 제품 환경성 평가 담당자'], ['해결 과제', '명칭 불일치, 소재·공정 혼재, 단위 불일치'], ['제공 기능', '후보 제시, 단위 환산, 근거 비교·승인']],
  nums: [
    ['Top-1 정답률', '1위 후보가 정답인 비율'],
    ['Top-3 정답률', '정답이 상위 3개 후보 안에 있는 비율'],
    ['1회 최대 분석 행 수', '한 번에 올릴 수 있는 BOM 행 수'],
  ],
  where: {
    h2: '적용 범위', sub: 'LCA 4단계 중 목록분석(LCI)의 데이터셋 연결 단계',
    stage3: ['③ 영향평가 (LCIA)', '배출계수 참고 표시 · 인증용 계산은 범위 밖'], // 코드에 carbon(배출계수) 필드가 있어 X1 이 구현된 것으로 본다
  },
  problem: {
    h2: '매칭의 3가지 난제',
    cards: [
      [['명칭', ' 불일치'], '약어·영문·별칭이라 글자 검색으로는 놓침'],
      [['소재·공정', ' 혼재'], '국가 DB는 소재와 가공을 따로 담는데 BOM은 같이 씀'],
      [['단위', ' 불일치'], '그대로는 계산이 안 되고, 모자란 값은 담당자에게 물어야 함'],
    ],
  },
  solution: {
    h2: '처리 구조', sub: 'AI 검색 · 규칙 검증 · 담당자 확정',
    cards: [
      ['의미 기반 검색', '품목 사전으로 약어를 풀고, 의미가 가까운 데이터셋을 찾아 같은 이름은 하나로 묶음'],
      ['규칙 기반 검증', '단위 환산, 소재·공정에 맞지 않는 후보 뒤로, 모자란 값 입력 요청'],
      ['담당자 확정', '후보와 근거를 나란히 보고 확정. 확정한 행만 내보냄'],
    ],
  },
  expected: {
    h2: '기대 효과', sub: '목표이며 업무 시간 단축은 아직 측정하지 않았습니다',
    big: [['검색에서 ', '검증', ' 중심으로'], '반복 검색·단위 맞추기를 도구가 맡아, 담당자는 연결이 맞는지 확인에 집중'],
    small: [
      [['오연결 ', '사전 차단'], '소재 행에 공정 데이터셋이 붙는 연결은 규칙으로 막고, 소재·공정 통합 데이터셋은 이중 계산 위험 표시'],
      [['매칭 ', '근거 기록'], '순위·행 종류·최신판 여부를 후보마다 남겨 검토 기록으로 사용'],
    ],
  },
  evaluation: {
    pill: '평가 완료 · 참고용', h3: '성능 평가',
    body: '정답을 아는 시험 데이터로 Top-1 정답률·신뢰도를 측정했습니다. 가상 BOM 2000(AI가 만든 합성 데이터)과 공개 문서 표기(실제 문서 표기)를 나란히 보여 주며, 정답 라벨은 사람 검수 전입니다.',
    button: '성능 확인 보기',
  },
  start: '샘플 BOM으로 시작하기',
}

// 큰 숫자 ①②: 평가 API(A19 → A14)를 pick.js 로 읽은 가상 BOM 2000의 Top-1·Top-3. 값을 하드코딩하지 않는다. 못 읽으면 null → '-'
const loadRates = async () => {
  const { items } = await listEvalRuns()
  const picks = await Promise.all(items.map((i) => getEvalRun(i.run_id).then(pick)))
  const bulk = picks.find((p) => p.goldId === 'gold-bulk-v1')
  return bulk ? { top1: bulk.top1, top3: bulk.top3 } : null
}
const pct = (v) => (v == null ? '-' : `${(v * 100).toFixed(1)}%`)

const Cursor = ({ style }) => (
  <svg className="intro-cursor" width="30" height="34" viewBox="0 0 24 28" style={style} aria-hidden="true">
    <path d="M3 2l17 12-7.5 1.5L16 24l-3.5 1.6-3.6-8.3L3 22z" fill="#FFFFFF" stroke="#111827" strokeWidth="1.6" strokeLinejoin="round" />
  </svg>
)

const Wave = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M4 9c3-4 8-4 11 0s6 3 6 3" stroke="#1F5BD8" strokeWidth="2.4" strokeLinecap="round" />
    <path d="M3 15c3-4 8-4 11 0s6 3 6 3" stroke="#2A9D8F" strokeWidth="2.4" strokeLinecap="round" />
  </svg>
)

// 소개 화면 (시안 C, U5d). 숫자는 측정한 값만: 평가 숫자는 평가 API에서 읽고, 행 수 상한은 서버 제한값
const IntroPage = () => {
  const navigate = useNavigate()
  const [rates, setRates] = useState(null)

  useEffect(() => {
    let ignore = false
    loadRates().then((r) => !ignore && setRates(r)).catch(() => {})
    return () => { ignore = true }
  }, [])

  return (
    <div className="intro">
      <header className="intro-hero">
        <div className="intro-hero-top">
          <span className="intro-tag">{INTRO.tag}</span>
          <div className="intro-engine">
            <div className="intro-engine-row">
              {INTRO.engine[0]}
              <span className="intro-engine-ico"><Pictogram name="network" size={18} /></span>
            </div>
            <div className="intro-engine-sub">{INTRO.engine[1]}</div>
          </div>
        </div>
        <h1 className="intro-h1"><span className="intro-nb">{INTRO.h1[0]}</span> ↔ <span className="intro-nb">{INTRO.h1[1]}</span></h1>
        <p className="intro-lead">{INTRO.sub}</p>
        <p className="intro-lead">{INTRO.lead}</p>
      </header>

      <section className="intro-scene-wrap" aria-label="사용 흐름 예시">
        <div className="intro-scene">
          <div className="intro-screen" aria-hidden="true">
            <div className="intro-screen-brand"><Wave size={30} />LCI-Match</div>
            <div className="intro-screen-state">후보 준비 완료 · 승인 대기</div>
            <div className="intro-screen-table">
              <div className="intro-screen-head">
                <span style={{ width: 160 }}>입력 행</span>
                <span className="intro-bar" style={{ width: 90 }} /><span className="intro-bar" style={{ width: 90 }} /><span className="intro-bar" style={{ width: 80 }} />
              </div>
              <div className="intro-screen-body">
                <span className="intro-bar" style={{ width: 90 }} /><span className="intro-bar" style={{ width: 70 }} />
                <span className="intro-chip">확인 필요</span>
              </div>
            </div>
          </div>
          <svg className="lines" width="1040" height="790" viewBox="0 0 1040 790" fill="none" aria-hidden="true">
            <g stroke="#6B7280" strokeWidth="2" strokeLinecap="round">
              <path d="M225 328 V 362" />
              <path d="M225 420 V 468" />
              <path d="M372 521 H 528" />
              <path d="M930 704 V 726" />
            </g>
            <g fill="#6B7280">
              <path d="M225 370 l-7-11 h14z" />
              <path d="M225 478 l-7-11 h14z" />
              <path d="M538 521 l-11-7 v14z" />
              <path d="M930 736 l-7-11 h14z" />
            </g>
          </svg>
          <span className="intro-no" style={{ left: 237, top: 337 }}>②</span>
          <span className="intro-no" style={{ left: 237, top: 436 }}>③</span>
          <span className="intro-no" style={{ left: 445, top: 489 }}>④</span>
          <div className="intro-pop intro-pop-in">
            <div className="k">{INTRO.scene.input[0]}</div>
            <div className="v">{INTRO.scene.input[1]}<span>{INTRO.scene.input[2]}</span><span className="q">{INTRO.scene.input[3]}</span></div>
          </div>
          <Cursor style={{ left: 442, top: 244 }} />
          <div className="intro-pill"><Pictogram name="search" size={18} />{INTRO.scene.pill}</div>
          <div className="intro-pop intro-cands">
            <div className="intro-cands-head"><b>{INTRO.scene.head[0]}</b><span>{INTRO.scene.head[1]}</span></div>
            <div className="intro-cand top">
              <div><div className="n">{INTRO.scene.top[0]}</div><div className="m">{INTRO.scene.top[1]}</div></div>
              <span className="intro-badge">{INTRO.scene.top[2]}</span>
            </div>
            {INTRO.scene.others.map(([name, diff]) => (
              <div className="intro-cand other" key={name}>
                <div><span className="n">{name}</span><span className="m"> 소재</span></div>
                <span className="intro-badge gray">{diff}</span>
              </div>
            ))}
          </div>
          <div className="intro-pop intro-pop-unit">
            <div className="t"><Pictogram name="scale" size={20} strokeWidth={1.8} />{INTRO.scene.unit[0]}</div>
            <div className="d">{INTRO.scene.unit[1]}</div>
          </div>
          <div className="intro-approve">{INTRO.scene.approve}</div>
          <Cursor style={{ left: 1004, top: 768 }} />
        </div>
        <ol className="intro-steps">
          {INTRO.steps.map(([t, d]) => <li key={t}><b>{t}</b><span>{d}</span></li>)}
        </ol>
        <p className="intro-note">{INTRO.scene.note}</p>
      </section>

      <div className="intro-facts intro-in">
        <dl className="intro-facts-list">
          {INTRO.facts.map(([k, v]) => <div key={k}><dt>· {k}</dt><dd>{v}</dd></div>)}
        </dl>
        <div className="intro-nums">
          {[pct(rates?.top1), pct(rates?.top3), `${MAX_ROWS}행`].map((v, i) => (
            <div className="intro-num" key={INTRO.nums[i][0]}><span>{INTRO.nums[i][0]}<small>{INTRO.nums[i][1]}</small></span><b>{v}</b></div>
          ))}
        </div>
      </div>

      <section className="intro-where" aria-labelledby="intro-where-h">
        <div className="intro-in">
          <div className="intro-eyebrow">Where</div>
          <h2 className="intro-h2" id="intro-where-h" style={{ marginBottom: 10 }}>{INTRO.where.h2}</h2>
          <p className="intro-where-sub">{INTRO.where.sub}</p>
          <ol className="intro-stages">
            <li className="intro-stage">① 목적 및 범위 정의</li>
            <li className="intro-stage on" aria-current="step">② 목록분석 (LCI)<small>이 도구가 다루는 곳</small></li>
            <li className="intro-stage">{INTRO.where.stage3[0]}<small>{INTRO.where.stage3[1]}</small></li>
            <li className="intro-stage">④ 해석</li>
          </ol>
        </div>
      </section>

      <section className="intro-sec intro-in" aria-labelledby="intro-problem-h">
        <div className="intro-eyebrow">Problem</div>
        <h2 className="intro-h2" id="intro-problem-h">{INTRO.problem.h2}</h2>
        <div className="intro-cards">
          <article className="intro-card">
            <div className="intro-card-top">
              <h3><em>{INTRO.problem.cards[0][0][0]}</em>{INTRO.problem.cards[0][0][1]}</h3>
              <span className="intro-circle"><Pictogram name="name" /></span>
            </div>
            <p>{INTRO.problem.cards[0][1]}</p>
            <div className="eg">BOM ‘SPCC 냉연강판’ ↔ 데이터셋 ‘냉간압연강판’</div>
          </article>
          <article className="intro-card">
            <div className="intro-card-top">
              <h3><em>{INTRO.problem.cards[1][0][0]}</em>{INTRO.problem.cards[1][0][1]}</h3>
              <span className="intro-circle teal"><Pictogram name="layers" /></span>
            </div>
            <p>{INTRO.problem.cards[1][1]}</p>
            <div className="eg">‘분체도장 처리’는 공정 — 소재 데이터셋에 붙으면 틀림</div>
          </article>
          <article className="intro-card">
            <div className="intro-card-top">
              <h3><em>{INTRO.problem.cards[2][0][0]}</em>{INTRO.problem.cards[2][0][1]}</h3>
              <span className="intro-circle violet"><Pictogram name="ruler" /></span>
            </div>
            <p>{INTRO.problem.cards[2][1]}</p>
            <div className="eg">kg · EA · m² · spot · 회</div>
          </article>
        </div>
      </section>

      <div className="intro-arrow" aria-hidden="true">
        <svg width="44" height="64" viewBox="0 0 44 64" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M22 4v52M6 40l16 16 16-16" /></svg>
      </div>

      <section className="intro-sol intro-in" aria-labelledby="intro-sol-h">
        <div className="intro-eyebrow">Solution</div>
        <h2 className="intro-h2" id="intro-sol-h" style={{ marginBottom: 10 }}>{INTRO.solution.h2}</h2>
        <p className="intro-where-sub" style={{ marginBottom: 24 }}>{INTRO.solution.sub}</p>
        <div className="intro-cards">
          {[['ai', 'AI'], ['code', '코드'], ['human', '사람']].map(([cls, who], i) => (
            <article className="intro-card sol" key={cls}>
              <div className={`who ${cls}`}>{who}</div>
              <h3>{INTRO.solution.cards[i][0]}</h3>
              <p>{INTRO.solution.cards[i][1]}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="intro-exp intro-in" aria-labelledby="intro-exp-h">
        <div className="intro-eyebrow">Expected</div>
        <h2 className="intro-h2" id="intro-exp-h" style={{ marginBottom: 10 }}>{INTRO.expected.h2}</h2>
        <p className="intro-where-sub" style={{ marginBottom: 24 }}>{INTRO.expected.sub}</p>
        <div className="intro-exp-big">
          <h3>{INTRO.expected.big[0][0]}<em>{INTRO.expected.big[0][1]}</em>{INTRO.expected.big[0][2]}</h3>
          <p>{INTRO.expected.big[1]}</p>
        </div>
        <div className="intro-exp-small">
          <article className="intro-card">
            <div>
              <h3>{INTRO.expected.small[0][0][0]}<em>{INTRO.expected.small[0][0][1]}</em></h3>
              <p>{INTRO.expected.small[0][1]}</p>
            </div>
            <span className="intro-circle"><Pictogram name="shield" /></span>
          </article>
          <article className="intro-card">
            <div>
              <h3>{INTRO.expected.small[1][0][0]}<em>{INTRO.expected.small[1][0][1]}</em></h3>
              <p>{INTRO.expected.small[1][1]}</p>
            </div>
            <span className="intro-circle teal"><Pictogram name="doc" /></span>
          </article>
        </div>
      </section>

      <section className="intro-eval intro-in" aria-labelledby="intro-eval-h">
        <div className="intro-eval-card">
          <div>
            <span className="intro-pillwarn">{INTRO.evaluation.pill}</span>
            <h3 id="intro-eval-h">{INTRO.evaluation.h3}</h3>
            <p>{INTRO.evaluation.body}</p>
          </div>
          <Link className="intro-btn sm" to="/evaluation">{INTRO.evaluation.button}</Link>
        </div>
      </section>

      <section className="intro-start intro-in" aria-labelledby="intro-start-h">
        <h2 id="intro-start-h">{INTRO.start}</h2>
        <div className="intro-btns">
          <button type="button" className="intro-btn" onClick={() => navigate('/upload', { state: { sample: true } })}>샘플로 해 보기</button>
          <Link className="intro-btn ghost" to="/upload"><Pictogram name="upload" size={18} />BOM 올리기</Link>
        </div>
        <div>
        </div>
        <p className="intro-source">
          비상업 포트폴리오 프로젝트입니다. 샘플 BOM은 공개 자료를 바탕으로 한 가정이며 실제 업체 BOM이 아닙니다.<br />
          데이터 출처: 환경부·한국환경산업기술원 국가 LCI DB (ILCD 형식). 이용 조건은 원 출처를 따릅니다.
        </p>
      </section>
    </div>
  )
}

export default IntroPage
