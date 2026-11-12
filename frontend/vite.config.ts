import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/IssuerLens/',
  plugins: [react()],
  server: {
    port: 7777,
    proxy: {
      '/IssuerLens/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/IssuerLens/, ''),
      },
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: true,
      },
    },
  },
})
