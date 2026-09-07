import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { Document, Page } from 'react-pdf'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  List,
  Maximize2,
  Rows3,
  X,
  ZoomIn,
  ZoomOut
} from 'lucide-react'

type Props = {
  title: string
  pdfUrl?: string
  overrideUrl?: string
  overrideTitle?: string
  onAcceptDrop?: (payload: { url: string; name: string; kind: string }) => void
  onClearOverride?: () => void
  downloadName?: string
  counterpartLabel?: string
  onLocateCounterpart?: (payload: {
    selectedText: string
    page: number
    pageCount: number
  }) => void
}

export type PdfPaneHandle = {
  locateAndHighlight: (payload: { text: string; positionRatio: number }) => Promise<void>
}

type OutlineItem = {
  title: string
  pageIndex: number | null
  items: OutlineItem[]
}

type ViewMode = 'scroll' | 'single'

export const PdfPane = forwardRef<PdfPaneHandle, Props>(function PdfPane({
  title,
  pdfUrl,
  overrideUrl,
  overrideTitle,
  onAcceptDrop,
  onClearOverride,
  downloadName,
  counterpartLabel,
  onLocateCounterpart,
}: Props, ref) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pageRefs = useRef<Array<HTMLDivElement | null>>([])
  const isProgrammaticScrollRef = useRef(false)
  const pdfDocumentRef = useRef<any>(null)
  const scaleRef = useRef(1.0)
  const pinchRef = useRef<{ distance: number; scale: number } | null>(null)
  const [numPages, setNumPages] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [scale, setScale] = useState(1.0)
  const [zoomInput, setZoomInput] = useState('100')
  const [containerWidth, setContainerWidth] = useState<number | undefined>(undefined)
  const [outline, setOutline] = useState<OutlineItem[]>([])
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [mode, setMode] = useState<ViewMode>('scroll')
  const [dragOver, setDragOver] = useState(false)
  const [selectionMenu, setSelectionMenu] = useState<{
    x: number
    y: number
    text: string
    page: number
    canClearHighlight: boolean
  } | null>(null)

  const effectiveUrl = overrideUrl || pdfUrl
  const effectiveTitle = overrideUrl ? (overrideTitle || '已覆盖') : title

  useEffect(() => {
    setPageNumber(1)
    setOutline([])
    setOutlineOpen(false)
    setNumPages(0)
    setScale(1.0)
    setZoomInput('100')
    scaleRef.current = 1.0
    pdfDocumentRef.current = null
    pageRefs.current = []
  }, [pdfUrl, overrideUrl])

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

  useEffect(() => {
    scaleRef.current = scale
    setZoomInput(String(Math.round(scale * 100)))
  }, [scale])

  useEffect(() => {
    const scroller = scrollRef.current
    if (!scroller || !effectiveUrl) return

    const clampScale = (value: number) => Math.max(0.4, Math.min(3, Math.round(value * 100) / 100))
    const zoomAt = (nextScale: number, clientX: number, clientY: number) => {
      const previous = scaleRef.current
      const next = clampScale(nextScale)
      if (Math.abs(previous - next) < 0.005) return
      const rect = scroller.getBoundingClientRect()
      const localX = clientX - rect.left
      const localY = clientY - rect.top
      const contentX = scroller.scrollLeft + localX
      const contentY = scroller.scrollTop + localY
      const ratio = next / previous
      scaleRef.current = next
      setScale(next)
      window.setTimeout(() => {
        scroller.scrollLeft = contentX * ratio - localX
        scroller.scrollTop = contentY * ratio - localY
      }, 40)
    }

    const onWheel = (event: WheelEvent) => {
      // Desktop trackpad pinch gestures are exposed as ctrl+wheel by Chromium.
      if (!event.ctrlKey) return
      event.preventDefault()
      event.stopPropagation()
      const factor = Math.exp(-event.deltaY * 0.0025)
      zoomAt(scaleRef.current * factor, event.clientX, event.clientY)
    }
    const distance = (touches: TouchList) => {
      const dx = touches[0].clientX - touches[1].clientX
      const dy = touches[0].clientY - touches[1].clientY
      return Math.hypot(dx, dy)
    }
    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 2) return
      pinchRef.current = { distance: distance(event.touches), scale: scaleRef.current }
    }
    const onTouchMove = (event: TouchEvent) => {
      if (event.touches.length !== 2 || !pinchRef.current) return
      event.preventDefault()
      event.stopPropagation()
      const midpointX = (event.touches[0].clientX + event.touches[1].clientX) / 2
      const midpointY = (event.touches[0].clientY + event.touches[1].clientY) / 2
      const ratio = distance(event.touches) / Math.max(1, pinchRef.current.distance)
      zoomAt(pinchRef.current.scale * ratio, midpointX, midpointY)
    }
    const onTouchEnd = () => { pinchRef.current = null }

    scroller.addEventListener('wheel', onWheel, { passive: false })
    scroller.addEventListener('touchstart', onTouchStart, { passive: true })
    scroller.addEventListener('touchmove', onTouchMove, { passive: false })
    scroller.addEventListener('touchend', onTouchEnd)
    scroller.addEventListener('touchcancel', onTouchEnd)
    return () => {
      scroller.removeEventListener('wheel', onWheel)
      scroller.removeEventListener('touchstart', onTouchStart)
      scroller.removeEventListener('touchmove', onTouchMove)
      scroller.removeEventListener('touchend', onTouchEnd)
      scroller.removeEventListener('touchcancel', onTouchEnd)
    }
  }, [effectiveUrl])

  const fileOpts = useMemo(() => (effectiveUrl ? { url: effectiveUrl, withCredentials: true } : null), [effectiveUrl])

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
    pdfDocumentRef.current = doc
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

  function normalized(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '')
  }

  function clearHighlights() {
    const pane = containerRef.current
    if (!pane) return
    pane.querySelectorAll('.pdf-text-highlight').forEach((node) => node.classList.remove('pdf-text-highlight'))
    pane.querySelectorAll('.pdf-page-counterpart-highlight').forEach((node) => node.classList.remove('pdf-page-counterpart-highlight'))
  }

  function commitZoomInput() {
    const parsed = Number.parseFloat(zoomInput.replace('%', '').trim())
    if (!Number.isFinite(parsed)) {
      setZoomInput(String(Math.round(scaleRef.current * 100)))
      return
    }
    const percent = Math.max(40, Math.min(300, Math.round(parsed)))
    const nextScale = percent / 100
    scaleRef.current = nextScale
    setScale(nextScale)
    setZoomInput(String(percent))
  }

  function highlightPageText(page: number, query: string) {
    const pane = containerRef.current
    const pageElement = pageRefs.current[page - 1]
    if (!pane || !pageElement) return
    clearHighlights()
    const target = normalized(query)
    const spans = Array.from(
      pageElement.querySelectorAll<HTMLElement>('.react-pdf__Page__textContent span')
    )
    const values = spans.map((node) => normalized(node.textContent || ''))
    const wantedLength = Math.min(140, target.length)
    let bestStart = -1
    let bestEnd = -1
    let bestPrefix = 0

    // Find one contiguous text-layer span range whose concatenated content
    // matches the beginning of the aligned target.  Highlighting every small
    // span that merely occurred somewhere in the paragraph caused unrelated
    // repeated words/numbers to light up.
    for (let start = 0; start < values.length; start += 1) {
      let combined = ''
      for (let end = start; end < Math.min(values.length, start + 80); end += 1) {
        combined += values[end]
        if (!combined) continue
        const compareLength = Math.min(combined.length, wantedLength)
        let prefix = 0
        while (prefix < compareLength && combined[prefix] === target[prefix]) prefix += 1
        if (prefix > bestPrefix) {
          bestPrefix = prefix
          bestStart = start
          bestEnd = end
        }
        if (prefix < Math.min(6, compareLength) || combined.length >= wantedLength) break
      }
    }

    const minimumMatch = Math.min(12, target.length)
    if (bestStart >= 0 && bestPrefix >= minimumMatch) {
      for (let index = bestStart; index <= bestEnd; index += 1) {
        spans[index].classList.add('pdf-text-highlight')
      }
      return
    }

    // A title/caption is sometimes emitted as one large span.  Keep a narrow
    // single-span fallback instead of highlighting unrelated fragments.
    let fallbackIndex = -1
    let fallbackLength = 0
    values.forEach((value, index) => {
      if (value.length >= 6 && target.includes(value) && value.length > fallbackLength) {
        fallbackIndex = index
        fallbackLength = value.length
      }
    })
    if (fallbackIndex >= 0) spans[fallbackIndex].classList.add('pdf-text-highlight')
    else pageElement.classList.add('pdf-page-counterpart-highlight')
  }

  useImperativeHandle(ref, () => ({
    async locateAndHighlight({ text, positionRatio }) {
      const doc = pdfDocumentRef.current
      if (!doc || !numPages) return
      const hint = Math.max(1, Math.min(numPages, Math.round(positionRatio * Math.max(0, numPages - 1)) + 1))
      const order = Array.from({ length: numPages }, (_, index) => index + 1)
        .sort((a, b) => Math.abs(a - hint) - Math.abs(b - hint))
      const target = normalized(text)
      const needles = [target.slice(0, 120), target.slice(0, 60), target.slice(0, 24)]
        .filter((item) => item.length >= 6)
      let found = hint
      for (const page of order) {
        try {
          const pdfPage = await doc.getPage(page)
          const textContent = await pdfPage.getTextContent()
          const pageText = normalized(textContent.items.map((item: any) => item.str || '').join(' '))
          if (needles.some((needle) => pageText.includes(needle))) {
            found = page
            break
          }
        } catch {}
      }
      gotoPage(found)
      window.setTimeout(() => highlightPageText(found, text), 700)
    }
  }))

  function handleTextContextMenu(event: React.MouseEvent) {
    if (!onLocateCounterpart) return
    const target = event.target as HTMLElement
    const highlighted = Boolean(
      target.closest('.pdf-text-highlight') || target.closest('.pdf-page-counterpart-highlight')
    )
    const selection = window.getSelection()
    const text = selection?.toString().trim() || ''
    const selectedInPane = Boolean(text && containerRef.current?.contains(selection?.anchorNode ?? null))
    if (!selectedInPane && !highlighted) return
    const pageElement = target.closest<HTMLElement>('[data-pdf-page]')
    const selectedPage = Number(pageElement?.dataset.pdfPage || pageNumber)
    event.preventDefault()
    event.stopPropagation()
    setSelectionMenu({
      x: event.clientX,
      y: event.clientY,
      text: selectedInPane ? text.slice(0, 2000) : '',
      page: selectedPage,
      canClearHighlight: highlighted,
    })
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

  function handleDragOver(e: React.DragEvent) {
    if (!onAcceptDrop) return
    e.preventDefault()
    setDragOver(true)
  }
  function handleDragLeave() {
    setDragOver(false)
  }
  function handleDrop(e: React.DragEvent) {
    if (!onAcceptDrop) return
    e.preventDefault()
    setDragOver(false)
    try {
      const raw = e.dataTransfer.getData('application/x-paperreader-artifact') || e.dataTransfer.getData('text/plain')
      if (!raw) return
      const payload = JSON.parse(raw)
      if (!payload?.url) return
      const kind = String(payload.kind || '')
      const name = String(payload.name || 'preview')
      const isPdf = kind.includes('pdf') || /\.pdf$/i.test(name) || /\.pdf(\?|$)/i.test(payload.url)
      if (!isPdf) {
        alert('仅支持拖入 PDF 类文件')
        return
      }
      onAcceptDrop({ url: payload.url, name, kind })
    } catch (err) {
      console.error(err)
    }
  }

  if (!effectiveUrl) {
    return (
      <div
        className={`pdf-pane ${dragOver ? 'drop-target' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="pdf-toolbar">
          <div className="pdf-title">{title}</div>
        </div>
        <div className="pdf-empty muted">{onAcceptDrop ? '暂无 PDF · 可将左侧产物拖入此处' : '暂无 PDF'}</div>
      </div>
    )
  }

  return (
    <div
      className={`pdf-pane ${dragOver ? 'drop-target' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="pdf-toolbar">
        <div className="pdf-title" title={effectiveTitle}>
          {effectiveTitle}
          {overrideUrl && onClearOverride && (
            <button
              className="icon-btn"
              title="还原默认 PDF"
              style={{ marginLeft: 6 }}
              onClick={onClearOverride}
            >
              <X size={14} />
            </button>
          )}
        </div>
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
          <label className="zoom-input-wrap" title="手动输入缩放比例（40%–300%）">
            <input
              className="zoom-input"
              type="text"
              inputMode="numeric"
              aria-label="缩放百分比"
              value={zoomInput}
              onChange={(event) => setZoomInput(event.target.value.replace(/[^0-9.%]/g, ''))}
              onBlur={commitZoomInput}
              onFocus={(event) => event.currentTarget.select()}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  commitZoomInput()
                  event.currentTarget.blur()
                } else if (event.key === 'Escape') {
                  setZoomInput(String(Math.round(scaleRef.current * 100)))
                  event.currentTarget.blur()
                }
              }}
            />
            <span>%</span>
          </label>
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
          <a className="icon-btn" title="下载" href={effectiveUrl} download={downloadName || true}>
            <Download size={16} />
          </a>
        </div>
      </div>

      <div className="pdf-body" ref={containerRef}>
        {outlineOpen && outline.length > 0 && (
          <div className="pdf-outline">{renderOutline(outline)}</div>
        )}
        <div className="pdf-canvas-wrap" ref={scrollRef} onContextMenu={handleTextContextMenu}>
          <Document
            file={fileOpts ?? undefined}
            onLoadSuccess={onDocumentLoadSuccess}
            loading={<div className="muted" style={{ padding: 20 }}>加载中…</div>}
            error={<div className="muted" style={{ padding: 20 }}>无法加载 PDF</div>}
          >
            {numPages > 0 && mode === 'single' && (
              <div
                className="pdf-page-wrap"
                data-pdf-page={pageNumber}
                ref={(el) => { pageRefs.current[pageNumber - 1] = el }}
              >
                <Page
                  pageNumber={pageNumber}
                  scale={scale}
                  width={containerWidth}
                  renderTextLayer
                  renderAnnotationLayer
                />
              </div>
            )}
            {numPages > 0 && mode === 'scroll' && (
              <div className="pdf-scroll-stack">
                {Array.from({ length: numPages }, (_, i) => (
                  <div
                    key={`page-${i + 1}`}
                    className="pdf-page-wrap"
                    data-pdf-page={i + 1}
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
      {selectionMenu && (
        <>
          <div className="context-menu-overlay" onClick={() => setSelectionMenu(null)} />
          <div className="context-menu pdf-selection-menu" style={{ top: selectionMenu.y, left: selectionMenu.x }}>
            {selectionMenu.text && (
              <button
                className="context-menu-item"
                onClick={() => {
                  const selected = selectionMenu
                  setSelectionMenu(null)
                  onLocateCounterpart?.({
                    selectedText: selected.text,
                    page: selected.page,
                    pageCount: numPages,
                  })
                }}
              >
                跳转到{counterpartLabel || '对应内容'}并高亮
              </button>
            )}
            {selectionMenu.canClearHighlight && (
              <button
                className="context-menu-item"
                onClick={() => {
                  clearHighlights()
                  setSelectionMenu(null)
                  window.getSelection()?.removeAllRanges()
                }}
              >
                清除高亮
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
})
