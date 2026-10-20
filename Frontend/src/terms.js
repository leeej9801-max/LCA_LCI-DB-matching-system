// 화면 용어와 ⓘ 문구의 원천 (design/ux-revision-2.md "용어표"). 화면은 문구를 직접 쓰지 않고 키로 가져온다.
// 같은 개념은 모든 화면에서 이 label 하나만 쓴다. 용어표에 없는 용어를 여기에 더하지 않는다
const terms = {
  lci_dataset: {
    label: 'LCI 데이터셋',
    info: '소재·공정 하나의 투입·산출(자원, 에너지, 배출) 목록입니다. 국가 DB는 소재(1 kg 생산), 생산공정(1 kg 가공), 수송(1 ton·km), 폐기(1 kg 처리)처럼 나뉘어 있어, 부품 하나에는 소재와 공정 데이터셋이 함께 필요할 수 있습니다.',
  },
  candidate: { label: '후보', info: '입력 품명과 비슷하다고 자동으로 찾은 데이터셋입니다. 사람이 승인해야 확정됩니다.' },
  confidence: {
    label: '신뢰도',
    info: '후보가 맞을 것 같은 정도를 높음·보통·낮음으로 나눈 표시입니다. 의미가 가까운 정도와 규칙으로 정하며, 정답일 확률이 아닙니다. 데이터셋 자체의 품질(시간·지역·기술 대표성)과는 다른 개념입니다.',
  },
  veto: { label: '차단', info: '소재·공정이 분명히 다른 후보를 규칙으로 막은 것입니다. 예: 입력은 용융 도금인데 후보는 전기 도금.' },
  no_match: {
    label: '맞는 후보 없음',
    info: 'DB에 이 품목에 맞는 데이터셋이 없다고 판단한 행입니다. (평가 화면의 "정답 없음"과 같은 개념). 근거가 약해 참고용 후보만 있는 경우도 있습니다.',
  },
  rejected: { label: '반려', info: '제시된 후보가 맞지 않아 이 행을 다시 골라야 하는 상태입니다.' },
  excluded: { label: '제외', info: '이 행은 계산 대상이 아닌 것(예: 포장재, 서비스)으로 뺀 상태입니다.' },
  approved: { label: '승인', info: '이 행의 데이터셋을 확정한 상태입니다. 내보내기에는 승인된 행만 들어갑니다.' },
  conversion: {
    label: '단위 변환',
    info: '입력 수량·단위를 데이터셋의 기준 단위로 바꾸는 것입니다. 상태: "변환 없음"(단위가 같음), "변환됨", "개당 중량을 입력하세요", "두께·밀도를 입력하세요", "단위 확인 필요", "단위가 맞지 않음". 상태는 단위·수량을 바꿀 수 있는지만 말하며, 후보가 맞다는 뜻이 아닙니다.',
    // 변환 칸의 상태 문구 (info 의 "상태:" 와 같은 단어). input(missing): 입력이 필요할 때의 안내
    states: { ok: '변환 없음', converted: '변환됨', incompatible: '단위가 맞지 않음', needsBadge: '단위 확인 필요' },
    // Conversion.method(서버 값) → 화면 말. 값은 그대로 두고 표시만 바꾼다
    methods: {
      identity: '단위가 같음', factor: '단위 배수', unit_mass: '개수 × 개당 중량', 'area×thickness×density': '면적 × 두께 × 밀도',
      'volume×density': '부피 × 밀도', 'mass÷(thickness×density)': '질량 ÷ (두께 × 밀도)', 'mass÷density': '질량 ÷ 밀도',
    },
    input: (missing) => {
      if (missing.includes('단위')) return '단위 확인 필요'
      const w = missing.join('·')
      const last = w.charCodeAt(w.length - 1) - 0xac00 // 받침이 있으면 '을', 없으면 '를'
      return `${w}${last >= 0 && last < 11172 && last % 28 ? '을' : '를'} 입력하세요`
    },
  },
  reference_flow: {
    label: '기준 단위',
    info: '데이터셋의 값이 어떤 양을 기준으로 한 것인지입니다(예: 1 kg 생산). 국가 DB는 원단위로 만들어 대부분 1 kg 또는 1 ton입니다.',
  },
  duplicate_group: {
    label: '같은 이름 N건', // 화면에서 N 을 건수로 바꾼다: sameName(n)
    info: '이름이 같은 데이터셋이 N개 있다는 뜻입니다(연도·기관이 다름). 기본으로 최신판(가장 최근 연도)을 대표로 보여 줍니다.',
    latest: '최신판',
  },
  rank_mismatch: {
    label: '검색 결과 엇갈림',
    info: '글자가 같은 후보와 뜻이 비슷한 후보의 1위가 서로 다릅니다. 직접 비교해 보세요.',
  },
  emission_factor: {
    label: '배출계수',
    info: "연결한 데이터셋 1 기준 단위를 만들 때 나오는 온실가스를 이산화탄소 환산 kg으로 나타낸 값입니다(국가 LCI DB의 영향평가 결과, 기후변화). 내보낸 파일의 '추정 배출량'은 환산 값에 이 값을 곱한 참고용 숫자이며 인증용이 아닙니다.",
  },
  has_xml: {
    label: 'XML 보유 / 엑셀만',
    xml: 'XML 보유',
    excel: '엑셀만',
    info: 'XML이 있으면 투입·산출 상세로 계산할 수 있습니다. 엑셀만 있는 데이터셋은 목록 정보만 있어 이후 계산에서 빠집니다.',
  },
  data_quality: {
    label: '데이터 품질',
    info: '데이터셋이 내 제품에 얼마나 대표적인지 보는 항목입니다(시간·지역·기술). 오래되거나 지역이 다르면 주의. 후보의 신뢰도와는 별개입니다.',
  },
  input_role: {
    label: '행 종류', // BOM 파일의 열 이름은 "구분"(인식 규칙은 그대로). 화면 표시만 이 말
    info: 'BOM 행이 소재인지 공정인지입니다(파일의 "구분" 열). 소재면 소재·소재·공정 통합 데이터셋에서만, 공정이면 공정 데이터셋에서만 후보를 찾습니다. 비우면 가리지 않고 찾습니다.',
  },
  dataset_role: {
    label: '데이터셋 종류',
    info: '국가 DB 데이터셋을 소재, 공정, 소재·공정 통합, 수송, 폐기·재활용, 에너지로 나눈 것입니다. 이름과 분류로 정했으며 검색 범위를 좁히는 데만 씁니다.',
    // API 값(데이터셋 역할) → 화면 표시. 값 자체(비교에 쓰는 '합본' 등)는 바꾸지 않는다
    values: { 합본: '소재·공정 통합', '에너지·유틸리티': '에너지' },
  },
  combined: {
    label: '소재·공정 통합',
    info: '소재 생산과 가공이 한 데이터셋에 같이 들어 있습니다. 같은 부품의 소재 행·공정 행과 같이 쓰면 가공이 두 번 계산될 수 있습니다.',
  },
  no_candidate: {
    label: '맞는 후보 없음',
    info: '후보가 모두 규칙으로 막혔거나(차단), 국가 DB에 이 품목에 맞는 데이터셋이 없다고 본 행입니다.',
  },
  no_reference_unit: {
    label: '기준 단위 없음',
    info: '이 데이터셋은 국가 DB에 기준 단위가 적혀 있지 않아 양을 변환할 수 없습니다. 다른 데이터셋을 고르세요.',
  },
  gold_set: { label: '정답셋', info: '사람이 입력마다 정답 데이터셋을 달아 둔 시험 문제 모음입니다.' },
  no_answer: { label: '정답 없음', info: '정답이 "맞는 후보 없음"인 시험 문제입니다.' },
  top1: { label: 'Top-1', info: '정답이 있는 시험 문제 중 1위 후보가 정답인 비율입니다.' },
  top3: { label: 'Top-3', info: '정답이 있는 시험 문제 중 정답이 상위 3개 안에 있는 비율입니다.' },
  abstain_reject_rate: {
    label: '정답 없음 거부율',
    info: '정답 없음 문제에서 후보를 내지 않고 "맞는 후보 없음"으로 처리한 비율입니다.',
  },
  answer_type: {
    label: '정답 유형',
    values: { exact: '정확', proxy: '대용', none: '없음' },
    info: '정확: 입력과 맞는 데이터셋이 있음. 대용: 꼭 맞는 것은 없어 가장 가까운 것을 정답으로 봄. 없음: 국가 DB에 맞는 데이터셋이 없음.',
  },
  scoring: {
    label: '채점 기준',
    values: { A: '이름 일치', S: '최신판 일치' },
    info: '이름 일치: 같은 이름의 데이터셋이면 판·연도가 달라도 맞음. 최신판 일치: 같은 이름 중 최신판이어야 맞음.',
  },
  // 성능 확인 화면의 탭 (순서·이름 원천). goldId: 평가 리포트의 config.gold_id
  eval_tabs: [
    { key: 'mine', label: '내가 올린 BOM' },
    { key: 'bulk', label: '가상 BOM 2000 (검증용)', goldId: 'gold-bulk-v1' },
    { key: 'p1', label: '공개 문서 표기', goldId: 'gold-p1-v1' },
  ],
  // 성능 확인 화면 새 용어 (U11): Top-1·Top-3 정답률, Top-K 재현율, 95% 신뢰구간, Top-1 채택률
  top1_rate: { label: 'Top-1 정답률', info: '1순위 추천이 정답인 비율입니다. 같은 이름이면 판·연도가 달라도 정답으로 봅니다.' },
  top3_rate: { label: 'Top-3 정답률', info: '상위 3개 후보 안에 정답이 있는 비율입니다.' },
  recall_k: { label: 'Top-K 재현율', info: '상위 K개 후보 안에 정답이 있는 비율입니다. K를 늘릴수록 높아집니다.' },
  ci95: { label: '95% 신뢰구간', info: '같은 방식으로 다시 시험해도 대체로 이 범위 안에 든다는 뜻입니다. 품목이 적거나 서로 비슷하면 넓어집니다.' },
  approve_match: {
    label: 'Top-1 채택률',
    info: '사람이 승인한 품목 중 도구의 1순위를 그대로 고른 비율입니다. 정답이 없는 데이터라 정답률과 다릅니다.',
  },
  human_work: {
    label: '검토 결과 분포',
    info: '행마다 사람이 한 일을 하나로 나눈 것입니다. 1순위 승인, 후보 비교 선택, 수동 탐색, 미매칭·제외·반려, 미검토.',
  },
  no_ground_truth: {
    label: '정답 미보유 데이터',
    info: '올린 BOM에는 어느 데이터셋이 맞는지 아는 정답이 없습니다. 그래서 이 탭은 정답률을 계산하지 않고, 신뢰도 표시와 사람이 한 일만 보여 줍니다. 정답을 아는 시험 결과는 옆 탭을 보세요.',
  },
  // 평가 화면의 검색 방식 이름(케이스 코드 → 화면 말). 코드는 화면 본문에 쓰지 않는다
  eval_cases: {
    C2: '기본(글자+의미 합산)',
    'C2+D+Vd': '기본 + 사전 + 소재·공정 강등',
    'C2+G+D+Vd': '위 + 같은 이름 접기',
    'C1+G+D+Vd': '의미 검색 + 같은 이름 접기 + 사전 + 강등 (앱 현재)',
  },
  baseline: {
    label: '글자 일치 단독',
    info: '글자 일치만 쓰는 가장 단순한 방식입니다. 다른 방식이 이보다 나은지를 비교하는 기준입니다.',
  },
  ablation: { label: '단계별 기여', info: '방식을 하나씩 더할 때마다 정확도가 얼마나 달라지는지 보는 표입니다.' },
}

export const sameName = (n) => terms.duplicate_group.label.replace('N', n)
// 데이터셋 종류 값(API) → 화면 말
export const roleLabel = (v) => (v == null ? v : terms.dataset_role.values[v] ?? v)
// 서버·mock 이 만든 근거·설명 문장 속 내부 방식 이름을 화면 말로 바꾼다(값은 그대로, 표시만)
export const plainText = (s) => s
  .replaceAll('TF-IDF', '글자 일치').replaceAll('밀집', '의미 유사')
  .replaceAll("구분 '", "행 종류 '").replaceAll('합본', terms.combined.label)
  .replace(/중 최신(?!판)/g, `중 ${terms.duplicate_group.latest}`).replaceAll('환산:', `${terms.conversion.label}:`)

export default terms
