import { Link } from 'react-router'

const NotFoundPage = () => {
  return (
    <div className="head">
      <div>
        <h1>페이지를 찾을 수 없습니다</h1>
        <p><Link to="/">S1 업로드로 가기</Link></p>
      </div>
    </div>
  )
}

export default NotFoundPage
