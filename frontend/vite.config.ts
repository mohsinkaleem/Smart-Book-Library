import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/covers': 'http://localhost:8000',
    },
  },
  optimizeDeps: {
    exclude: ['react-reader'],
  },
})
