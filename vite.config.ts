import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Dev: `pnpm dev` serves the dashboard on :8443 and proxies /api to the
// FastAPI backend on :8000 (override with VITE_BACKEND_PROXY_TARGET).
// Prod: nginx (nginx.conf) or VITE_API_BASE_URL does the same job.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    host: '0.0.0.0',
    port: parseInt(process.env.PORT || '8443'),
    proxy: {
      '/api': { target: process.env.VITE_BACKEND_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true },
      '/healthz': { target: process.env.VITE_BACKEND_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true },
    },
  },
  preview: { host: '0.0.0.0', port: parseInt(process.env.PORT || '8443') },
})
