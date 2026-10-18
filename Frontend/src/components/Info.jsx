import { useEffect, useId, useRef, useState } from 'react'
import terms from '@/terms'

const WIDTH = 280 // 설명 상자 최대 폭(px). 화면이 좁으면 화면 폭 - 16

// ⓘ 설명 (ux-revision-2 R2). <Info term="veto" /> 는 terms.js 문구, <Info>문구</Info> 는 직접 쓴 문구.
// 마우스 올림·키보드 포커스로 열리고 클릭(터치)하면 고정된다. Esc·바깥 누름으로 닫힌다. 스크롤하면 따라간다.
// 상자는 fixed 로 띄워 표의 가로 스크롤 영역에 잘리지 않게 하고, 아래 공간이 모자라면 위로 연다
const Info = ({ term, children }) => {
  const id = useId()
  const ref = useRef(null)
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [pos, setPos] = useState(null)
  const text = term ? terms[term].info : children

  const place = () => {
    const r = ref.current.getBoundingClientRect()
    const width = Math.min(WIDTH, window.innerWidth - 16)
    const up = window.innerHeight - r.bottom < 140 && r.top > window.innerHeight - r.bottom
    setPos({
      width,
      left: Math.min(Math.max(8, r.left), window.innerWidth - width - 8),
      ...(up ? { bottom: window.innerHeight - r.top + 6 } : { top: r.bottom + 6 }),
    })
  }
  const show = () => { place(); setOpen(true) }
  const hide = () => { setOpen(false); setPinned(false) }

  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && hide()
    const onDown = (e) => !ref.current.contains(e.target) && hide()
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    window.addEventListener('scroll', place, true) // Tab 포커스가 화면을 스크롤해도 닫히지 않게 위치만 다시 잡는다
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])

  return (
    <span className="info" ref={ref} onMouseEnter={show} onMouseLeave={() => !pinned && setOpen(false)}>
      <button
        type="button" className="info-btn" aria-label="설명" aria-expanded={open} aria-describedby={id}
        onFocus={show} onBlur={() => !pinned && setOpen(false)}
        // 열린 설명만 닫고 Esc 가 바깥(S3 패널 닫기 등)으로 가지 않게 한다
        onKeyDown={(e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); hide() } }}
        onClick={() => (pinned ? hide() : (show(), setPinned(true)))}
      >ⓘ</button>
      <span id={id} role="tooltip" className="tip" hidden={!open} style={pos ?? undefined}>{text}</span>
    </span>
  )
}

export default Info
