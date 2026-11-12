import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The data comes from the Hub API (hub/, `uvicorn backend.api:app`).
// The dev server forwards /api/* to it, so the browser never talks to the API directly.
const API_TARGET = process.env.HUB_API || 'http://127.0.0.1:8000'
// Live feed service (live/app.py in this repo): /live/* -> the service.
const LIVE_TARGET = process.env.LIVE_API || 'http://127.0.0.1:8003'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 7777,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/live': {
        target: LIVE_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/live/, ''),
      },
    },
  },
})
