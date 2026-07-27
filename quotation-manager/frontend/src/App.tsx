import { Navigate, Route, Routes } from 'react-router-dom'
import BookingSearchPage from './pages/BookingSearchPage'
import QuotationEditorPage from './pages/QuotationEditorPage'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Routes>
        <Route path="/" element={<BookingSearchPage />} />
        <Route path="/quotation/:bookingId" element={<QuotationEditorPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
