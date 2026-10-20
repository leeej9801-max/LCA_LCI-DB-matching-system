import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useMatch } from 'react-router'
import Reason from '@/components/Reason'
import { readRecent } from '@/pages/evaluation/recentSessions'

const ADMIN = [
  ['/ingest', '적재 리포트'],
  ['/dictionary', '사전·규칙'],
  ['/history', '이력'],
  ['/validation', '검증·계산'],
]

const Layout = () => {
  // 결과(S2)는 세션이 있어야 열 수 있다. S2·S3 경로면 그 세션, 다른 화면에서는 브라우저가 기억한 가장 최근 세션으로 연다
  const { pathname } = useLocation()
  const sessionId = useMatch('/results/:sessionId/*')?.params.sessionId ?? readRecent()[0]?.id
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
          <NavLink to="/" className="logo">LCI-Match</NavLink>
          <nav className="topnav" aria-label="작업 흐름">
            <NavLink to="/" end>소개</NavLink>
            <NavLink to="/upload">업로드</NavLink>
            {sessionId
              ? <NavLink to={`/results/${sessionId}`}>결과</NavLink>
              : <Reason text="먼저 BOM을 업로드하세요"><span aria-disabled="true">결과</span></Reason>}
            <NavLink to="/datasets">데이터셋</NavLink>
            <NavLink to="/evaluation">성능 확인</NavLink>
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
