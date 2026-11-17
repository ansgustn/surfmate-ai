import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// /api/* 요청을 FastAPI 백엔드(기본 localhost:8010, API_URL 로 변경)로 넘긴다
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.API_URL ?? 'http://localhost:8010',
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
