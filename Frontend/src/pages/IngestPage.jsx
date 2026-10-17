// S5 적재 리포트 — 틀만 있다. 화면 내용은 해당 T 작업에서 채운다.
const IngestPage = () => {
  return (
    <>
      <div className="head">
        <h1>S5 적재 리포트</h1>
        <span className="meta">FR-101~103</span>
      </div>
      <aside className="api" aria-label="이 화면이 쓰는 API">
        <h3>이 화면이 쓰는 API</h3>
        <table>
          <tbody>
            <tr><td className="i">A09</td><td className="m">POST</td><td>{'/api/admin/ingest'}</td></tr>
            <tr><td className="i">A10</td><td className="m">GET</td><td>{'/api/admin/ingest/reports'}</td></tr>
          </tbody>
        </table>
      </aside>
    </>
  )
}

export default IngestPage
