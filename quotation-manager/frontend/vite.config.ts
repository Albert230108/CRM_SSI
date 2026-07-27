import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  envDir: '../',
  // Served behind nginx at /quotation/ (see nginx/default.conf), so built asset URLs
  // and the SPA's router basename both need this prefix - see main.tsx's BrowserRouter.
  base: '/quotation/',
})
