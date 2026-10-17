// S8 검토 이력 — 틀만 있다. 화면 내용은 해당 T 작업에서 채운다.
const HistoryPage = () => {
  return (
    <>
      <div className="head">
        <h1>S8 검토 이력</h1>
        <span className="meta">FR-803</span>
      </div>
      <aside className="api" aria-label="이 화면이 쓰는 API">
        <h3>이 화면이 쓰는 API</h3>
        <table>
          <tbody>
            <tr><td className="i">A15</td><td className="m">GET</td><td>{'/api/sessions/{id}/audit?row=&type=&limit=&offset='}</td></tr>
          </tbody>
        </table>
      </aside>
    </>
  )
}

export default HistoryPage
