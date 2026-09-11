import { Navigate, Route, Routes } from 'react-router-dom'
import BookingSearchPage from './pages/BookingSearchPage'
import FilesPage from './pages/FilesPage'
import NewQuotationPage from './pages/NewQuotationPage'
import QuotationEditorPage from './pages/QuotationEditorPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Routes>
        <Route path="/" element={<BookingSearchPage />} />
        <Route path="/new" element={<NewQuotationPage />} />
        <Route path="/files" element={<FilesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        {/* Must stay last: any other single path segment is read as a Beds24 booking id. */}
        <Route path="/:bookingId" element={<QuotationEditorPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}
