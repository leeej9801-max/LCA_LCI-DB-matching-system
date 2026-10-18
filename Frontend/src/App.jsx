import { BrowserRouter, Routes, Route } from 'react-router'
import Layout from '@/components/Layout'
import IntroPage from '@pages/IntroPage'
import UploadPage from '@pages/UploadPage'
import ResultsPage from '@pages/ResultsPage'
import CandidateReviewPage from '@pages/CandidateReviewPage'
import DatasetsPage from '@pages/DatasetsPage'
import IngestPage from '@pages/IngestPage'
import DictionaryPage from '@pages/DictionaryPage'
import EvaluationPage from '@pages/EvaluationPage'
import HistoryPage from '@pages/HistoryPage'
import ValidationPage from '@pages/ValidationPage'
import NotFoundPage from '@pages/NotFoundPage'

const App = () => {
  const paths = [
    { path: '/', element: <IntroPage /> },
    { path: '/upload', element: <UploadPage /> },
    { path: '/datasets', element: <DatasetsPage /> },
    { path: '/ingest', element: <IngestPage /> },
    { path: '/dictionary', element: <DictionaryPage /> },
    { path: '/evaluation', element: <EvaluationPage /> },
    { path: '/history', element: <HistoryPage /> },
    { path: '/validation', element: <ValidationPage /> },
    { path: '*', element: <NotFoundPage /> },
  ]
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          {/* S3는 S2 위에 열리는 패널이라 S2의 자식 라우트 */}
          <Route path="/results/:sessionId" element={<ResultsPage />}>
            <Route path="rows/:rowId" element={<CandidateReviewPage />} />
          </Route>
          {paths.map((v) => <Route key={v.path} path={v.path} element={v.element} />)}
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
