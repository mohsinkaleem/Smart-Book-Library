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
    // Pre-bundled, not excluded.
    //
    // Excluding it left epub.js and its CommonJS dependencies to the browser's
    // own ESM loader, which cannot read a named export out of CJS: every EPUB
    // opened in `npm run dev` failed with "does not provide an export named
    // 'DOMParser'" from @xmldom/xmldom, and the reader showed "Failed to load
    // EPUB reader library". A production build never hit it, because Rollup
    // does that interop at build time — so the whole EPUB half of the reader
    // was untestable locally.
    include: ['react-reader', 'epubjs'],
  },
})
