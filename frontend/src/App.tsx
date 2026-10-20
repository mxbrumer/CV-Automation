import { Route, Routes } from 'react-router'
import Layout from './components/Layout'
import AddJob from './pages/AddJob'
import Home from './pages/Home'
import JobDetail from './pages/JobDetail'
import Jobs from './pages/Jobs'
import Matches from './pages/Matches'
import Placeholder from './pages/Placeholder'
import Queue from './pages/Queue'
import Review from './pages/Review'
import ReviewDetail from './pages/ReviewDetail'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="add" element={<AddJob />} />
        <Route path="matches" element={<Matches />} />
        <Route path="review" element={<Review />} />
        <Route path="review/:id" element={<ReviewDetail />} />
        <Route path="queue" element={<Queue />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="jobs/:id" element={<JobDetail />} />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Route>
    </Routes>
  )
}
