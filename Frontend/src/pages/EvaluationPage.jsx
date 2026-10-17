// S7 평가 — 틀만 있다. 화면 내용은 해당 T 작업에서 채운다.
const EvaluationPage = () => {
  return (
    <>
      <div className="head">
        <h1>S7 평가</h1>
        <span className="meta">FR-901~903</span>
      </div>
      <aside className="api" aria-label="이 화면이 쓰는 API">
        <h3>이 화면이 쓰는 API</h3>
        <table>
          <tbody>
            <tr><td className="i">A13</td><td className="m">POST</td><td>{'/api/eval/runs'}</td></tr>
            <tr><td className="i">A14</td><td className="m">GET</td><td>{'/api/eval/runs/{id}'}</td></tr>
            <tr><td className="i">A19<b>+</b></td><td className="m">GET</td><td>{'/api/eval/runs'}</td></tr>
          </tbody>
        </table>
      </aside>
    </>
  )
}

export default EvaluationPage
