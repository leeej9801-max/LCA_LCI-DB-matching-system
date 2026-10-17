import { Link } from 'react-router'

// S1 BOM 업로드 — 틀만 있다. 화면 내용은 해당 T 작업에서 채운다.
const UploadPage = () => {
  return (
    <>
      <div className="head">
        <h1>S1 BOM 업로드</h1>
        <span className="meta">FR-301</span>
      </div>
      {/* 개발 확인용: T5에서 실제 업로드로 바뀐다 */}
      {import.meta.env.VITE_API_MOCK === '1' && <p><Link to="/results/7f3a9c21d0b4">예시 세션 열기</Link></p>}
      <aside className="api" aria-label="이 화면이 쓰는 API">
        <h3>이 화면이 쓰는 API</h3>
        <table>
          <tbody>
            <tr><td className="i">A20<b>+</b></td><td className="m">POST</td><td>{'/api/sessions/preview'}</td></tr>
            <tr><td className="i">A08</td><td className="m">GET</td><td>{'/api/sample.csv'}</td></tr>
            <tr><td className="i">A01</td><td className="m">POST</td><td>{'/api/sessions'}</td></tr>
          </tbody>
        </table>
      </aside>
    </>
  )
}

export default UploadPage
