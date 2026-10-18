// 업로드·진행 단계의 오류(스펙 07 오류 code 표)를 화면 문구로. 서버 detail 이 이미 한국어라 code 가 없으면 그대로 쓴다
export const uploadErrorText = (e) => {
  switch (e.code) {
    case 'FILE_TOO_LARGE': return '파일이 너무 큽니다. 5MB 이하로 줄여 올려 주세요.'
    case 'TOO_MANY_ROWS': return `행이 너무 많습니다(${e.meta?.rows?.toLocaleString?.() ?? '?'}행). 한 번에 ${e.meta?.limit?.toLocaleString?.() ?? '2,000'}행까지 올릴 수 있습니다.`
    case 'MISSING_COLUMN': return `필수 컬럼 ${(e.meta?.missing ?? []).join('·')}을(를) 찾지 못했습니다. 컬럼 대응에서 파일의 컬럼을 골라 주세요.`
    case 'UNKNOWN_COLUMN': return `파일에 없는 컬럼을 골랐습니다: ${(e.meta?.columns ?? []).join(', ')}. 컬럼을 다시 골라 주세요.`
    case 'INVALID_MAPPING': return '컬럼 대응 형식이 올바르지 않습니다. 컬럼을 다시 골라 주세요.'
    case 'QUEUE_FULL': return '지금 처리 중인 작업이 많습니다. 잠시 후 다시 시도해 주세요.'
    case 'UNREADABLE_FILE': return e.detail
    default: return e.detail
  }
}

// 다시 시도가 의미 있는 오류: 대기열이 찼거나(429) 서버·Ollama 쪽 일시 문제. 파일·컬럼 문제는 파일을 바꿔야 한다
export const retryable = (e) => e.status === 429 || e.status == null || e.status >= 500
