import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('pdfjs-dist') || id.includes('react-pdf')) return 'pdf'
          if (id.includes('react-markdown') || id.includes('remark-') || id.includes('rehype-') || id.includes('katex')) return 'markdown'
          if (id.includes('node_modules/react') || id.includes('react-dom')) return 'react'
        }
      }
    },
    // PDF.js includes its own rendering engine; its isolated chunk is
    // intentionally larger than ordinary application chunks.
    chunkSizeWarningLimit: 700
  },
  server: {
    port: 5173
  }
})
