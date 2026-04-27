import { useEffect, useMemo, useRef, useState } from 'react'
import { Document, Page } from 'react-pdf'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  List,
  Maximize2,
  Rows3,
  ZoomIn,
  ZoomOut
} from 'lucide-react'

type Props = {
  title: string
  pdfUrl?: string
}

type OutlineItem = {
  title: string
  pageIndex: number | null
  items: OutlineItem[]
}

type ViewMode = 'scroll' | 'single'

export function PdfPane({ title, pdfUrl }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pageRefs = useRef<Array<HTMLDivElement | null>>([])
  const isProgrammaticScrollRef = useRef(false)
  const [numPages, setNumPages] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [scale, setScale] = useState(1.0)
  const [containerWidth, setContainerWidth] = useState<number | undefined>(undefined)
  const [outline, setOutline] = useState<OutlineItem[]>([])
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [mode, setMode] = useState<ViewMode>('scroll')

  useEffect(() => {
    setPageNumber(1)
    setOutline([])
    setOutlineOpen(false)
    setNumPages(0)
    pageRefs.current = []
  }, [pdfUrl])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(Math.max(200, entry.contentRect.width - 24))
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fileOpts = useMemo(() => (pdfUrl ? { url: pdfUrl } : null), [pdfUrl])

  async function mapOutlineItem(doc: any, item: any): Promise<OutlineItem> {
    let pageIndex: number | null = null
    try {
      const dest = typeof item.dest === 'string' ? await doc.getDestination(item.dest) : item.dest
      if (dest && dest[0]) {
        pageIndex = await doc.getPageIndex(dest[0])
      }
    } catch {
      pageIndex = null
    }
    const items: OutlineItem[] = item.items
      ? await Promise.all(item.items.map((c: any) => mapOutlineItem(doc, c)))
      : []
    return { title: item.title, pageIndex, items }
  }

  async function onDocumentLoadSuccess(doc: any) {
    setNumPages(doc.numPages)
    pageRefs.current = new Array(doc.numPages).fill(null)
    try {
      const raw = await doc.getOutline()
      if (raw) {
        const built = await Promise.all(raw.map((item: any) => mapOutlineItem(doc, item)))
        setOutline(built)
      }
    } catch {
      setOutline([])
    }
  }

  function gotoPage(p: number) {
    if (!numPages) return
    const target = Math.max(1, Math.min(numPages, p))
    setPageNumber(target)
    if (mode === 'scroll') {
      const el = pageRefs.current[target - 1]
      const scroller = scrollRef.current
      if (el && scroller) {
        isProgrammaticScrollRef.current = true
        scroller.scrollTo({ top: el.offsetTop - 8, behavior: 'smooth' })
        window.setTimeout(() => {
          isProgrammaticScrollRef.current = false
        }, 600)
      }
    }
  }

  // Track current page in scroll mode by detecting which page is closest to top
  useEffect(() => {
    if (mode !== 'scroll' || !numPages) return
    const scroller = scrollRef.current
    if (!scroller) return
    const handler = () => {
      if (isProgrammaticScrollRef.current) return
      const top = scroller.scrollTop + 40
      let current = 1
      for (let i = 0; i < pageRefs.current.length; i++) {
        const el = pageRefs.current[i]
        if (!el) continue
        if (el.offsetTop <= top) current = i + 1
        else break
      }
      setPageNumber((prev) => (prev === current ? prev : current))
    }
    scroller.addEventListener('scroll', handler, { passive: true })
    return () => scroller.removeEventListener('scroll', handler)
  }, [mode, numPages])

  function renderOutline(items: OutlineItem[], depth = 0) {
    return (
      <ul className="outline-list">
        {items.map((it, idx) => (
          <li key={idx} style={{ paddingLeft: depth * 10 }}>
            <button
              className="outline-link"
              onClick={() => {
                if (it.pageIndex !== null) gotoPage(it.pageIndex + 1)
              }}
            >
              {it.title}
            </button>
            {it.items.length > 0 && renderOutline(it.items, depth + 1)}
          </li>
        ))}
      </ul>
    )
  }

  if (!pdfUrl) {
    return (
      <div className="pdf-pane">
        <div className="pdf-toolbar">
          <div className="pdf-title">{title}</div>
        </div>
        <div className="pdf-empty muted">暂无 PDF</div>
      </div>
    )
  }

  return (
    <div className="pdf-pane">
      <div className="pdf-toolbar">
        <div className="pdf-title" title={title}>{title}</div>
        <div className="pdf-controls">
          <button
            className="icon-btn"
            title="目录"
            onClick={() => setOutlineOpen((v) => !v)}
            disabled={!outline.length}
          >
            <List size={16} />
          </button>
          <button className="icon-btn" title="上一页" onClick={() => gotoPage(pageNumber - 1)}>
            <ChevronLeft size={16} />
          </button>
          <input
            className="page-input"
            type="number"
            min={1}
            max={numPages || 1}
            value={pageNumber}
            onChange={(e) => gotoPage(parseInt(e.target.value || '1', 10))}
          />
          <span className="muted small">/ {numPages || '—'}</span>
          <button className="icon-btn" title="下一页" onClick={() => gotoPage(pageNumber + 1)}>
            <ChevronRight size={16} />
          </button>
          <span className="sep" />
          <button className="icon-btn" title="缩小" onClick={() => setScale((s) => Math.max(0.4, s - 0.1))}>
            <ZoomOut size={16} />
          </button>
          <span className="muted small" style={{ minWidth: 38, textAlign: 'center' }}>
            {Math.round(scale * 100)}%
          </span>
          <button className="icon-btn" title="放大" onClick={() => setScale((s) => Math.min(3, s + 0.1))}>
            <ZoomIn size={16} />
          </button>
          <button className="icon-btn" title="适合宽度" onClick={() => setScale(1.0)}>
            <Maximize2 size={16} />
          </button>
          <span className="sep" />
          <button
            className={`icon-btn ${mode === 'scroll' ? 'active' : ''}`}
            title="滚动阅读"
            onClick={() => setMode('scroll')}
          >
            <Rows3 size={16} />
          </button>
          <button
            className={`icon-btn ${mode === 'single' ? 'active' : ''}`}
            title="单页模式"
            onClick={() => setMode('single')}
          >
            <FileText size={16} />
          </button>
          <a className="icon-btn" title="下载" href={pdfUrl} download>
            <Download size={16} />
          </a>
        </div>
      </div>

      <div className="pdf-body" ref={containerRef}>
        {outlineOpen && outline.length > 0 && (
          <div className="pdf-outline">{renderOutline(outline)}</div>
        )}
        <div className="pdf-canvas-wrap" ref={scrollRef}>
          <Document
            file={fileOpts ?? undefined}
            onLoadSuccess={onDocumentLoadSuccess}
            loading={<div className="muted" style={{ padding: 20 }}>加载中…</div>}
            error={<div className="muted" style={{ padding: 20 }}>无法加载 PDF</div>}
          >
            {numPages > 0 && mode === 'single' && (
              <Page
                pageNumber={pageNumber}
                scale={scale}
                width={containerWidth}
                renderTextLayer
                renderAnnotationLayer
              />
            )}
            {numPages > 0 && mode === 'scroll' && (
              <div className="pdf-scroll-stack">
                {Array.from({ length: numPages }, (_, i) => (
                  <div
                    key={`page-${i + 1}`}
                    className="pdf-page-wrap"
                    ref={(el) => {
                      pageRefs.current[i] = el
                    }}
                  >
                    <Page
                      pageNumber={i + 1}
                      scale={scale}
                      width={containerWidth}
                      renderTextLayer
                      renderAnnotationLayer
                    />
                    <div className="pdf-page-label muted small">第 {i + 1} 页</div>
                  </div>
                ))}
              </div>
            )}
          </Document>
        </div>
      </div>
    </div>
  )
}
