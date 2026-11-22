import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The Django API runs on :8001 (agent-tree owns :8000/:5173); proxying keeps one origin, no CORS
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8001' },
  },
})
