import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { initToken } from './lib/apiClient'
import './index.css'

initToken()

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter basename="/quotation">
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
