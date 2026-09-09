import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, normalizePath } from 'vite'
import { viteStaticCopy } from 'vite-plugin-static-copy'

const frontendDir = fileURLToPath(new URL('.', import.meta.url))
const pdfjsAssetGlob = (directory: string) =>
  normalizePath(resolve(frontendDir, `node_modules/pdfjs-dist/${directory}/*`))

export default defineConfig({
  plugins: [
    react(),
    // PDF.js needs the packed CMap files to load CID-keyed CJK fonts (e.g.
    // Fandol subsets embedded by xdvipdfmx, which carry no ToUnicode map).
    // Without them the viewer silently drops every CJK glyph. The standard
    // font data covers the base-14 PDF fonts. Served at /cmaps and
    // /standard_fonts in both `vite dev` and the built bundle that the
    // packaged app serves from the FastAPI static mount.
    viteStaticCopy({
      targets: [
        { src: pdfjsAssetGlob('cmaps'), dest: 'cmaps' },
        { src: pdfjsAssetGlob('standard_fonts'), dest: 'standard_fonts' }
      ]
    })
  ],
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
