import { useEffect, useId, useRef, useState } from 'react'
import terms from '@/terms'

// "용어 설명" 링크 하나 (U7 규칙 5). 열 머리·탭마다 있던 ⓘ 대신 표 위에 하나만 두고, 누르면 terms.js 의 용어 목록을 연다.
// keys: terms.js 키 배열(화면에서 쓰는 용어만). 바깥을 누르거나 Esc 를 누르면 닫고 포커스를 링크로 돌려준다
const TermsHelp = ({ keys }) => {
  const id = useId()
  const wrap = useRef(null)
  const button = useRef(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => !wrap.current.contains(e.target) && setOpen(false)
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      e.stopPropagation() // 열린 목록만 닫고 바깥(패널 닫기)으로 가지 않게
      setOpen(false)
      button.current.focus()
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [open])

  return (
    <span className="terms-help" ref={wrap}>
      <button ref={button} type="button" className="terms-link" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>용어 설명</button>
      {open && (
        <div id={id} className="terms-pop" role="region" aria-label="용어 설명">
          <dl>
            {keys.map((k) => (
              <div key={k}>
                <dt>{terms[k].label}</dt>
                <dd>{terms[k].info}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </span>
  )
}

export default TermsHelp
