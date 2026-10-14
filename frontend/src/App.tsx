import { Route, Routes } from 'react-router'
import Layout from './components/Layout'
import Home from './pages/Home'
import Matches from './pages/Matches'
import Placeholder from './pages/Placeholder'
import Review from './pages/Review'
import ReviewDetail from './pages/ReviewDetail'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="matches" element={<Matches />} />
        <Route path="review" element={<Review />} />
        <Route path="review/:id" element={<ReviewDetail />} />
        <Route path="queue" element={<Placeholder title="Queue" plan="13" />} />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Route>
    </Routes>
  )
}
