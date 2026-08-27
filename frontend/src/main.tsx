import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { installSessionExpiryDetection } from './lib/sessionExpiry'
import { installRefreshDiagnostics } from './lib/refreshDiagnostics'
import './index.css'

installSessionExpiryDetection()
installRefreshDiagnostics()

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
