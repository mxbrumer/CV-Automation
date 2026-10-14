import { Route, Routes } from 'react-router'
import Layout from './components/Layout'
import Home from './pages/Home'
import Matches from './pages/Matches'
import Placeholder from './pages/Placeholder'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="matches" element={<Matches />} />
        <Route path="review" element={<Placeholder title="Review" plan="12" />} />
        <Route path="review/:id" element={<Placeholder title="Review" plan="12" />} />
        <Route path="queue" element={<Placeholder title="Queue" plan="13" />} />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Route>
    </Routes>
  )
}
