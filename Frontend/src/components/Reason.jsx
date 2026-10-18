import { useId } from 'react'

// 꺼진 것의 이유 (ux-revision-2 R3). 꺼진 버튼·링크·체크박스를 감싼다. when 이 거짓이면 children 만 그린다.
// disabled 요소는 호버·포커스 이벤트를 주지 않으므로 감싸는 요소가 포커스를 받고(Tab), 올림·포커스 때 이유 한 줄을 보인다.
// 스크린리더는 aria-describedby 로 이유를 읽는다
const Reason = ({ when = true, text, children }) => {
  const id = useId()
  if (!when) return children
  return (
    <span className="reason" tabIndex={0} aria-describedby={id}>
      {children}
      <span id={id} role="tooltip" className="tip">{text}</span>
    </span>
  )
}

export default Reason
