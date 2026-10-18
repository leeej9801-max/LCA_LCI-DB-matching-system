import { isMock } from '@/api/client'

// 예시 데이터 표시 (ux-revision-2 R4). path 의 API 가 mock 이면 한 줄, 실제 서버면 아무것도 그리지 않는다
const MockNotice = ({ path, children = '예시 데이터입니다. 실제 서버가 계산한 값이 아닙니다.' }) =>
  isMock(path) ? <p className="mock-note" role="note">{children}</p> : null

export default MockNotice
