import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useMatch } from 'react-router'

const ADMIN = [
  ['/ingest', '적재 리포트'],
  ['/dictionary', '사전·규칙'],
  ['/evaluation', '평가'],
  ['/history', '이력'],
  ['/validation', '검증·계산'],
]

const Layout = () => {
  // 결과(S2)는 세션이 있어야 열 수 있다. S2·S3 경로에 있을 때만 링크가 된다
  const sessionId = useMatch('/results/:sessionId/*')?.params.sessionId
  const { pathname } = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)
  const buttonRef = useRef(null)
  const adminActive = ADMIN.some(([to]) => pathname.startsWith(to))

  // 관리 메뉴: 바깥을 누르거나 Esc 를 누르면 닫는다 (Esc 는 버튼으로 포커스 복귀)
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e) => !menuRef.current.contains(e.target) && setMenuOpen(false)
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      setMenuOpen(false)
      buttonRef.current.focus()
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-in">
          <span className="logo">LCI-Match</span>
          <nav className="topnav" aria-label="작업 흐름">
            <NavLink to="/" end>업로드</NavLink>
            {sessionId
              ? <NavLink to={`/results/${sessionId}`}>결과</NavLink>
              : <span aria-disabled="true" title="업로드로 세션을 먼저 만드세요">결과</span>}
            <NavLink to="/datasets">데이터셋</NavLink>
          </nav>
          <div className="admin" ref={menuRef}>
            <button
              ref={buttonRef}
              type="button"
              className={adminActive ? 'active' : undefined}
              aria-expanded={menuOpen}
              aria-controls="admin-menu"
              onClick={() => setMenuOpen((v) => !v)}
            >
              관리 <span aria-hidden="true">▾</span>
            </button>
            {menuOpen && (
              <ul id="admin-menu" className="menu">
                {ADMIN.map(([to, label]) => (
                  <li key={to}><NavLink to={to} onClick={() => setMenuOpen(false)}>{label}</NavLink></li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}

export default Layout
