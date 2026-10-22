import { HIGH_COVERAGE_GOAL, HIGH_ERROR_GOAL, STYLE_NAMES } from './evalText.js'

// 평가 리포트(A14)에서 화면에 쓸 값을 고르는 한 곳 (U8 1절). 리포트 맨 위의 metrics·confidence_levels·ablation 은
// 다른 조합(C2) 기준이라 쓰지 않는다. 앱 조합과 신뢰도 규칙의 값만 아래 상수로 꺼낸다.
// 값이 없으면 지어내지 않고 오류를 던진다(화면이 불러오기 실패로 보여 준다).
export const APP = 'C1+G+D+Vd'
export const RULE = 'R1 τ=0.55' // 개발셋에서 고정한 규칙. 리포트의 "선택" 표시(측정 세트에서 다시 고른 것)는 쓰지 않는다
export const LEVELS = ['높음', '보통', '낮음']
export const RECALL_KS = [1, 3, 10, 30]
export const METHODS = ['C2', 'C2+D+Vd', 'C2+G+D+Vd', APP] // 화면의 방식 A~D
const PAIR_OF = { 'gold-bulk-v1': 'gold-p1-v1', 'gold-p1-v1': 'gold-bulk-v1' }

// 고른 기록과 나란히 보일 기록의 gold_id. 가상 BOM 2000은 공개 문서 표기와, 공개 문서 표기는 가상 BOM 2000과 비교한다(U9)
export const compareGoldId = (goldId) => PAIR_OF[goldId]

const need = (v, what) => {
  if (v == null) throw new Error(`리포트에 ${what} 값이 없습니다`)
  return v
}

export const pick = (report) => {
  const recall = need(report.recall_at_k?.[APP]?.A, `recall_at_k[${APP}].A`)
  const rule = need(report.confidence_rules?.[APP]?.candidates?.find((c) => c.name === RULE), `confidence_rules[${APP}] ${RULE}`)
  const none = need(report.no_answer_by_case?.[APP], `no_answer_by_case[${APP}]`)
  const levels = Object.fromEntries(LEVELS.map((l) => [l, { rows: need(rule.levels[l]?.rows, `${l} 행 수`), acc: need(rule.levels[l]?.acc_A, `${l} 정답률`) }]))
  const high = levels['높음']
  const styles = report.slices?.[APP]?.input_style ?? {}
  const pair = (c) => need(report.pair_counts?.cases?.[c]?.A, `pair_counts.cases[${c}].A`)
  return {
    goldId: report.config.gold_id,
    total: report.gold_stats.total,
    answerable: recall.n,
    top1: recall.top1,
    top3: recall.top3,
    recall: RECALL_KS.map((k) => need(recall[`top${k}`], `top${k}`)),
    levels,
    highRows: high.rows,
    highCoverage: rule.high_coverage,
    highCoverageCi: rule.ci.high_coverage,
    highError: rule.high_error_A, // = 1 - levels["높음"].acc
    highErrorCi: rule.ci.high_error_A,
    noAnswer: {
      noneRows: none.none.rows, noneFound: none.none.no_answer, // 정답이 "없음"인 행 중 도구도 "없음"이라 한 수
      ansRows: none.answerable.rows, ansWrong: none.answerable.no_answer, // 정답이 있는데 "없음"이라 한 수
    },
    // 입력 유형별 첫 추천 정답률. 정답 있는 행이 없거나 표본이 작은(small) 유형, 이름 목록에 없는 키는 뺀다
    inputStyles: Object.keys(STYLE_NAMES).filter((k) => styles[k] && styles[k].answerable > 0 && !styles[k].small && styles[k].top1_A != null)
      .map((k) => ({ key: k, name: STYLE_NAMES[k], top1: styles[k].top1_A, n: styles[k].answerable })),
    methods: METHODS.map((c) => need(report.recall_at_k?.[c]?.A?.top1, `recall_at_k[${c}].A.top1`)),
    pairBase: need(report.pair_counts?.base, 'pair_counts.base'),
    pairs: Object.fromEntries(METHODS.filter((c) => c !== report.pair_counts.base).map((c) => [c, pair(c)])),
  }
}

// 100개를 올렸을 때 사람이 할 일. 훑어보고 승인 = 높음 비율, 3개 중 고르기 = 상위 3개 정답률 - 높음 비율(음수면 0), 직접 찾기 = 나머지
export const humanWork = (p) => {
  const approve = Math.round(p.highCoverage * 100)
  const choose = Math.min(100 - approve, Math.max(0, Math.round((p.top3 - p.highCoverage) * 100)))
  return { approve, choose, find: 100 - approve - choose }
}

// 목표 판정 한 곳(U10). 합격 = 높음 비율 ≥ 45% 그리고 높음 오류율 점추정 ≤ 10%.
// full(목표 충족) | partial(오류율만 충족: 높음 비율이 목표에 못 미침) | miss(오류율 > 10%). 구간 상한이 10%를 넘는지(rangeOver)도 같이 준다
export const goalOf = (p) => ({
  badge: p.highError > HIGH_ERROR_GOAL ? 'miss' : p.highCoverage >= HIGH_COVERAGE_GOAL ? 'full' : 'partial',
  rangeOver: p.highErrorCi[1] > HIGH_ERROR_GOAL,
})
