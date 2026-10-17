// S6 사전·규칙 — 틀만 있다. 화면 내용은 해당 T 작업에서 채운다.
const DictionaryPage = () => {
  return (
    <>
      <div className="head">
        <h1>S6 사전·규칙</h1>
        <span className="meta">FR-201·202·502</span>
      </div>
      <aside className="api" aria-label="이 화면이 쓰는 API">
        <h3>이 화면이 쓰는 API</h3>
        <table>
          <tbody>
            <tr><td className="i">A11</td><td className="m">GET</td><td>{'/api/dictionary?q=&verified='}</td></tr>
            <tr><td className="i">A11</td><td className="m">PUT</td><td>{'/api/dictionary/{entry_id}'}</td></tr>
            <tr><td className="i">A12</td><td className="m">GET</td><td>{'/api/veto-rules'}</td></tr>
          </tbody>
        </table>
      </aside>
    </>
  )
}

export default DictionaryPage
