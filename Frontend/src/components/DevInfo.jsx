// 개발 정보 (ux-revision-2 R6): API·FR·화면 ID 표. 개발 모드에서만 그리고 프로덕션 빌드에서는 아무것도 내지 않는다
const DevInfo = ({ children }) => {
  if (!import.meta.env.DEV) return null
  return (
    <details className="devinfo">
      <summary>개발 정보</summary>
      {children}
    </details>
  )
}

export default DevInfo
