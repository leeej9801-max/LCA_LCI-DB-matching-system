// S9 검증·계산 — 틀만 있다. 화면 내용은 해당 T 작업에서 채운다.
const ValidationPage = () => {
  return (
    <>
      <div className="head">
        <h1>S9 검증·계산</h1>
        <span className="meta">FR-1101~1106</span>
      </div>
      <aside className="api" aria-label="이 화면이 쓰는 API">
        <h3>이 화면이 쓰는 API</h3>
        <table>
          <tbody>
            <tr><td className="i">A16</td><td className="m">GET</td><td>{'/api/validation/reports'}</td></tr>
            <tr><td className="i">A17</td><td className="m">POST</td><td>{'/api/sessions/{id}/footprint'}</td></tr>
            <tr><td className="i">A18</td><td className="m">GET</td><td>{'/api/sessions/{id}/footprint/report'}</td></tr>
          </tbody>
        </table>
      </aside>
    </>
  )
}

export default ValidationPage
