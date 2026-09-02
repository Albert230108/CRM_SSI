import { Navigate, Route, Routes } from 'react-router-dom'
import BookingSearchPage from './pages/BookingSearchPage'
import NewQuotationPage from './pages/NewQuotationPage'
import QuotationEditorPage from './pages/QuotationEditorPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Routes>
        <Route path="/" element={<BookingSearchPage />} />
        <Route path="/new" element={<NewQuotationPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/quotation/:bookingId" element={<QuotationEditorPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
