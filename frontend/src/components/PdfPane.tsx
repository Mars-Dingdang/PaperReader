import {
  forwardRef,
  useEffect,
  useLayoutEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState
} from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { PDF_DOCUMENT_OPTIONS } from '../lib/pdfDocumentOptions'
import { buildSyntheticOutline, type OutlineItem } from '../lib/pdfOutline'
import { buildSpanIndex, locateNeedle, normalized, paintRange, prefixMatchScore, type SpanIndex } from '../lib/pdfText'
import type { AnnotationItem as ApiAnnotationItem, FigureItem as ApiFigureItem } from '../lib/api'
import { usePageText } from '../hooks/usePageText'
import { usePdfZoom } from '../hooks/usePdfZoom'
import { usePdfSearch } from '../hooks/usePdfSearch'
import {
  BookMarked,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Images,
  Link2,
  Link2Off,
  List,
  Maximize2,
  Rows3,
  Search,
  X,
  ZoomIn,
  ZoomOut
} from 'lucide-react'

export type AnnotationItem = ApiAnnotationItem

export type FigureItem = ApiFigureItem

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
  onAskAI?: (payload: { selectedText: string; page: number }) => void
  annotations?: AnnotationItem[]
  onCreateAnnotation?: (payload: {
    page: number
    quote: string
    color: string
    note: string
    positionRatio: number
  }) => Promise<void> | void
  onDeleteAnnotation?: (id: string) => Promise<void> | void
  onExportNotes?: () => void
  initialPosition?: { page: number; ratio: number } | null
  onProgressChange?: (page: number, ratio: number) => void
  onUserScrollRatio?: (ratio: number) => void
  syncEnabled?: boolean
  onToggleSync?: () => void
  figures?: FigureItem[]
  outline?: OutlineItem[] | null
  onActivate?: () => void
}

pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

export type PdfPaneHandle = {
  locateAndHighlight: (payload: {
    text: string
    highlightText?: string
    positionRatio: number
  }) => Promise<void>
  scrollToRatio: (ratio: number) => void
  openSearch: () => void
}

type ViewMode = 'scroll' | 'single'

const OVERLAY_CLASSES = [
  'pdf-text-highlight',
  'pdf-search-highlight',
  'pdf-search-current',
  'pdf-annotation-highlight',
  'pdf-annotation-yellow',
  'pdf-annotation-green',
  'pdf-annotation-blue',
  'pdf-annotation-pink'
]

const ANNOTATION_COLORS = ['yellow', 'green', 'blue', 'pink']

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
  onAskAI,
  annotations = [],
  onCreateAnnotation,
  onDeleteAnnotation,
  onExportNotes,
  initialPosition,
  onProgressChange,
  onUserScrollRatio,
  syncEnabled,
  onToggleSync,
  figures = [],
  outline = null,
  onActivate
}: Props, ref) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pageRefs = useRef<Array<HTMLDivElement | null>>([])
  const isProgrammaticScrollRef = useRef(false)
  const pdfDocumentRef = useRef<any>(null)
  const scaleRef = useRef(1.0)
  const zoomStackRef = useRef<HTMLDivElement | null>(null)
  const pageRatiosRef = useRef<Array<number | null>>([])
  const [numPages, setNumPages] = useState(0)
  const [ratioTick, setRatioTick] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [scale, setScale] = useState(1.0)
  const [zoomInput, setZoomInput] = useState('100')
  const [containerWidth, setContainerWidth] = useState<number | undefined>(undefined)
  const [outlineState, setOutlineState] = useState<OutlineItem[]>([])
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [outlineLoading, setOutlineLoading] = useState(false)
  const [outlineReady, setOutlineReady] = useState(false)
  const [outlineSource, setOutlineSource] = useState<'native' | 'generated' | null>(null)
  const [mode, setMode] = useState<ViewMode>('scroll')
  const [dragOver, setDragOver] = useState(false)
  const [selectionMenu, setSelectionMenu] = useState<{
    x: number
    y: number
    text: string
    page: number
    canClearHighlight: boolean
    annotationId: string | null
  } | null>(null)
  const [noteDraft, setNoteDraft] = useState('')
  const [counterpart, setCounterpart] = useState<{
    page: number
    text: string
    highlight: string
  } | null>(null)
  const [renderRange, setRenderRange] = useState<{ start: number; end: number }>({ start: 1, end: 1 })
  const [figuresOpen, setFiguresOpen] = useState(false)

  const annotationsRef = useRef<AnnotationItem[]>(annotations)
  annotationsRef.current = annotations
  const counterpartRef = useRef(counterpart)
  counterpartRef.current = counterpart
  const overrideActive = Boolean(overrideUrl)
  const centerCurrentMatchRef = useRef(false)
  const syncEmitRef = useRef(0)
  const progressTimerRef = useRef<ReturnType<typeof setTimeout> | 0>(0)
  const progressValueRef = useRef<{ page: number; ratio: number } | null>(null)
  const restoredPositionRef = useRef(false)
  const renderWaitersRef = useRef<Map<number, Array<() => void>>>(new Map())

  const effectiveUrl = overrideUrl || pdfUrl
  const effectiveTitle = overrideUrl ? (overrideTitle || '已覆盖') : title

  const { getPageText } = usePageText({ docRef: pdfDocumentRef, activeKey: effectiveUrl || '' })

  const updateRenderRange = () => {
    const scroller = scrollRef.current
    if (!scroller || mode !== 'scroll' || !numPages) return
    const top = scroller.scrollTop - 700
    const bottom = scroller.scrollTop + scroller.clientHeight + 700
    let first = numPages
    let last = 1
    for (let i = 0; i < pageRefs.current.length; i += 1) {
      const el = pageRefs.current[i]
      if (!el) continue
      const elTop = el.offsetTop
      const elBottom = elTop + el.offsetHeight
      if (elBottom >= top && elTop <= bottom) {
        first = Math.min(first, i + 1)
        last = Math.max(last, i + 1)
      }
    }
    if (first > last) return
    const start = Math.max(1, first - 1)
    const end = Math.min(numPages, last + 1)
    setRenderRange((prev) => (prev.start === start && prev.end === end ? prev : { start, end }))
  }

  const search = usePdfSearch({
    getPageText,
    numPages,
    goto: (page) => {
      centerCurrentMatchRef.current = true
      gotoPage(page)
    },
    onRepaint: () => repaintRenderedPages()
  })

  usePdfZoom({
    scrollerRef: scrollRef,
    zoomStackRef,
    scaleRef,
    scale,
    setScale,
    activeKey: effectiveUrl || ''
  })

  useEffect(() => {
    setPageNumber(1)
    setOutlineState([])
    setOutlineOpen(false)
    setOutlineLoading(false)
    setOutlineReady(false)
    setOutlineSource(null)
    setNumPages(0)
    setScale(1.0)
    setZoomInput('100')
    scaleRef.current = 1.0
    pdfDocumentRef.current = null
    pageRefs.current = []
    pageRatiosRef.current = []
    renderWaitersRef.current.clear()
    setCounterpart(null)
    setRenderRange({ start: 1, end: 1 })
    setFiguresOpen(false)
    if (progressTimerRef.current) clearTimeout(progressTimerRef.current)
    progressTimerRef.current = 0
    progressValueRef.current = null
    restoredPositionRef.current = false
    if (zoomStackRef.current) {
      zoomStackRef.current.style.transform = ''
      zoomStackRef.current.style.willChange = ''
    }
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
    // The .pdf-body element only exists once a URL is set; on a fresh load the
    // first mount renders the empty branch, so the observer must re-attach
    // when the PDF actually appears (otherwise fit-width stays broken).
  }, [effectiveUrl])

  useEffect(() => {
    scaleRef.current = scale
    setZoomInput(String(Math.round(scale * 100)))
    updateRenderRange()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scale])

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
    pageRatiosRef.current = new Array(doc.numPages).fill(null)
    // Page aspect ratios come from the page dictionaries (no rendering), so
    // the wrappers can be sized deterministically from the very first render
    // onward — independent of when canvas draws complete.
    doc.getPage(1).then((first: any) => {
      const fallback = first.view[3] / first.view[2]
      Promise.all(
        Array.from({ length: doc.numPages }, (_, i) =>
          doc.getPage(i + 1).then((p: any) => p.view[3] / p.view[2]).catch(() => fallback)
        )
      ).then((ratios: number[]) => {
        if (pdfDocumentRef.current === doc) {
          pageRatiosRef.current = ratios
          setRatioTick((t) => t + 1)
        }
      })
    }).catch(() => {})
    setOutlineLoading(true)
    setOutlineReady(false)
    try {
      if (outline?.length) {
        if (pdfDocumentRef.current === doc) {
          setOutlineState(outline)
          setOutlineSource('native')
        }
      } else {
        const raw = await doc.getOutline()
        if (raw?.length) {
          const built = await Promise.all(raw.map((item: any) => mapOutlineItem(doc, item)))
          if (pdfDocumentRef.current === doc) {
            setOutlineState(built)
            setOutlineSource('native')
          }
        } else {
          const built = await buildSyntheticOutline(doc)
          if (pdfDocumentRef.current === doc) {
            setOutlineState(built)
            setOutlineSource(built.length ? 'generated' : null)
          }
        }
      }
    } catch {
      if (pdfDocumentRef.current === doc) {
        setOutlineState([])
        setOutlineSource(null)
      }
    } finally {
      if (pdfDocumentRef.current === doc) {
        setOutlineLoading(false)
        setOutlineReady(true)
      }
    }
  }

  // A backend-provided outline (document structure endpoint) arriving after
  // the document loaded replaces the synthetic one.
  useEffect(() => {
    if (outline?.length) {
      setOutlineState(outline)
      setOutlineSource('native')
      setOutlineReady(true)
      setOutlineLoading(false)
    }
  }, [outline])

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

  function clearOverlayClasses(pageEl: HTMLElement) {
    pageEl.querySelectorAll(OVERLAY_CLASSES.map((c) => `.${c}`).join(',')).forEach((node) => {
      const el = node as HTMLElement
      for (const cls of OVERLAY_CLASSES) el.classList.remove(cls)
    })
    pageEl.querySelectorAll('[data-annotation-id]').forEach((node) => {
      delete (node as HTMLElement).dataset.annotationId
    })
  }

  function paintCounterpart(pageEl: HTMLElement, index: SpanIndex, payload: { text: string; highlight: string }) {
    const highlightNeedle = payload.highlight.trim()
    if (highlightNeedle) {
      const at = index.text.indexOf(normalized(highlightNeedle))
      if (at >= 0) {
        paintRange(index, at, at + normalized(highlightNeedle).length, 'pdf-text-highlight')
        return true
      }
    }
    const range = locateNeedle(index, payload.text)
    if (range) {
      paintRange(index, range.start, range.start + range.length, 'pdf-text-highlight')
      return true
    }
    // A title/caption is sometimes emitted as one large span.  Keep a narrow
    // single-span fallback instead of highlighting unrelated fragments.
    let fallbackLength = 0
    const target = normalized(payload.text)
    for (const entry of index.spans) {
      const value = normalized(entry.el.textContent || '')
      if (value.length >= 6 && target.includes(value) && value.length > fallbackLength) {
        fallbackLength = value.length
      }
    }
    if (fallbackLength >= 6) {
      for (const entry of index.spans) {
        const value = normalized(entry.el.textContent || '')
        if (value.length === fallbackLength && target.includes(value)) {
          entry.el.classList.add('pdf-text-highlight')
          return true
        }
      }
    }
    return false
  }

  function paintQuote(
    pageEl: HTMLElement,
    index: SpanIndex,
    quote: string,
    id: string,
    classNames: string
  ): boolean {
    const needle = normalized(quote)
    if (!needle) return false
    let at = index.text.indexOf(needle)
    let length = needle.length
    if (at < 0) {
      const range = locateNeedle(index, quote)
      if (!range) return false
      at = range.start
      length = range.length
    }
    paintRange(index, at, at + length, classNames)
    for (const entry of index.spans) {
      if (entry.end <= at || entry.start >= at + length) continue
      if (!entry.el.dataset.annotationId) entry.el.dataset.annotationId = id
    }
    return true
  }

  function applyOverlays(page: number, attempt = 0) {
    const pageEl = pageRefs.current[page - 1]
    if (!pageEl) return
    const index = buildSpanIndex(pageEl)
    if (!index) {
      // Text layer may still be mounting after the canvas render callback.
      if (attempt < 15) window.setTimeout(() => applyOverlays(page, attempt + 1), 150)
      return
    }
    clearOverlayClasses(pageEl)

    const cp = counterpartRef.current
    let counterpartMissing = false
    if (cp && cp.page === page) {
      counterpartMissing = !paintCounterpart(pageEl, index, cp)
    }

    const searchState = search.stateRef.current
    if (searchState.open && searchState.matches.length) {
      for (let i = 0; i < searchState.matches.length; i += 1) {
        const match = searchState.matches[i]
        if (match.page !== page) continue
        if (i === searchState.current) {
          paintRange(index, match.start, match.start + match.length, 'pdf-search-highlight pdf-search-current')
        } else {
          paintRange(index, match.start, match.start + match.length, 'pdf-search-highlight')
        }
      }
      const currentMatch = searchState.matches[searchState.current]
      if (centerCurrentMatchRef.current && currentMatch?.page === page) {
        centerCurrentMatchRef.current = false
        const entry = index.spans.find((s) => currentMatch.start < s.end && currentMatch.start >= s.start)
        entry?.el.scrollIntoView({ block: 'center' })
      }
    }

    if (!overrideActive) {
      for (const annotation of annotationsRef.current) {
        if (annotation.page !== page || !annotation.quote) continue
        paintQuote(
          pageEl,
          index,
          annotation.quote,
          annotation.id,
          `pdf-annotation-highlight pdf-annotation-${annotation.color}`
        )
      }
    }

    if (counterpartMissing) pageEl.classList.add('pdf-page-counterpart-highlight')
  }

  function repaintRenderedPages() {
    for (let i = 0; i < pageRefs.current.length; i += 1) {
      const el = pageRefs.current[i]
      if (el?.querySelector('.react-pdf__Page__textContent')) applyOverlays(i + 1)
    }
  }

  function handlePageRendered(page: number) {
    const waiters = renderWaitersRef.current.get(page)
    if (waiters) {
      renderWaitersRef.current.delete(page)
      for (const resolve of waiters) resolve()
    }
    applyOverlays(page)
  }

  function whenPageRendered(page: number): Promise<void> {
    const el = pageRefs.current[page - 1]
    if (el?.querySelector('.react-pdf__Page__textContent')) return Promise.resolve()
    return new Promise((resolve) => {
      const list = renderWaitersRef.current.get(page) || []
      list.push(resolve)
      renderWaitersRef.current.set(page, list)
      window.setTimeout(resolve, 8000)
    })
  }

  function clearHighlights() {
    setCounterpart(null)
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

  useImperativeHandle(ref, () => ({
    async locateAndHighlight({ text, highlightText, positionRatio }) {
      const doc = pdfDocumentRef.current
      if (!doc || !numPages) return
      const hint = Math.max(1, Math.min(numPages, Math.round(positionRatio * Math.max(0, numPages - 1)) + 1))
      // Score every page by the longest prefix of the target it contains;
      // ties and misses fall back to the position hint.  Whole-document scan
      // is cheap because page texts are cached.
      const highlightTarget = normalized(highlightText || '')
      const blockTarget = normalized(text)
      let bestPage = hint
      let bestScore = 0
      for (let page = 1; page <= numPages; page += 1) {
        const pageText = await getPageText(page)
        const score = Math.max(
          prefixMatchScore(pageText, highlightTarget),
          prefixMatchScore(pageText, blockTarget)
        )
        if (score > bestScore || (score > 0 && score === bestScore && Math.abs(page - hint) < Math.abs(bestPage - hint))) {
          bestScore = score
          bestPage = page
        }
      }
      setCounterpart({ page: bestPage, text, highlight: highlightText || '' })
      gotoPage(bestPage)
      await whenPageRendered(bestPage)
      applyOverlays(bestPage)
    },
    scrollToRatio(ratio: number) {
      const scroller = scrollRef.current
      if (!scroller || mode !== 'scroll') return
      const clamped = Math.max(0, Math.min(1, ratio))
      isProgrammaticScrollRef.current = true
      scroller.scrollTop = clamped * Math.max(0, scroller.scrollHeight - scroller.clientHeight)
      updateRenderRange()
      window.setTimeout(() => {
        isProgrammaticScrollRef.current = false
      }, 120)
    },
    openSearch() {
      search.openSearch()
    }
  }))

  function handleTextContextMenu(event: React.MouseEvent) {
    const target = event.target as HTMLElement
    const highlighted = Boolean(
      target.closest('.pdf-text-highlight') || target.closest('.pdf-page-counterpart-highlight')
    )
    const annotationEl = target.closest<HTMLElement>('[data-annotation-id]')
    const selection = window.getSelection()
    const text = selection?.toString().trim() || ''
    const selectedInPane = Boolean(text && containerRef.current?.contains(selection?.anchorNode ?? null))
    if (!selectedInPane && !highlighted && !annotationEl) return
    const pageElement = target.closest<HTMLElement>('[data-pdf-page]')
    const selectedPage = Number(pageElement?.dataset.pdfPage || pageNumber)
    event.preventDefault()
    event.stopPropagation()
    setNoteDraft('')
    setSelectionMenu({
      x: event.clientX,
      y: event.clientY,
      text: selectedInPane ? text.slice(0, 2000) : '',
      page: selectedPage,
      canClearHighlight: highlighted,
      annotationId: annotationEl?.dataset.annotationId || null
    })
  }

  async function submitAnnotation(color: string) {
    const menu = selectionMenu
    if (!menu || !onCreateAnnotation || !menu.text) return
    setSelectionMenu(null)
    window.getSelection()?.removeAllRanges()
    await onCreateAnnotation({
      page: menu.page,
      quote: menu.text,
      color,
      note: noteDraft.trim(),
      positionRatio: numPages > 1 ? (menu.page - 1) / (numPages - 1) : 0
    })
  }

  // Track current page in scroll mode by detecting which page is closest to
  // top; the same handler drives virtualization, synced scrolling, and
  // reading-progress reporting.
  useEffect(() => {
    if (mode !== 'scroll' || !numPages) return
    const scroller = scrollRef.current
    if (!scroller) return

    const emitProgress = (page: number, ratio: number) => {
      progressValueRef.current = { page, ratio }
      if (progressTimerRef.current) clearTimeout(progressTimerRef.current)
      progressTimerRef.current = setTimeout(() => {
        progressTimerRef.current = 0
        if (progressValueRef.current) {
          onProgressChange?.(progressValueRef.current.page, progressValueRef.current.ratio)
        }
      }, 2000)
    }

    const handler = () => {
      const top = scroller.scrollTop + 40
      let current = 1
      for (let i = 0; i < pageRefs.current.length; i += 1) {
        const el = pageRefs.current[i]
        if (!el) continue
        if (el.offsetTop <= top) current = i + 1
        else break
      }
      setPageNumber((prev) => (prev === current ? prev : current))
      updateRenderRange()
      if (isProgrammaticScrollRef.current) return
      const denominator = Math.max(1, scroller.scrollHeight - scroller.clientHeight)
      const ratio = Math.max(0, Math.min(1, scroller.scrollTop / denominator))
      emitProgress(current, ratio)
      const now = Date.now()
      if (now - syncEmitRef.current > 120) {
        syncEmitRef.current = now
        onUserScrollRatio?.(ratio)
      }
    }
    scroller.addEventListener('scroll', handler, { passive: true })
    return () => {
      scroller.removeEventListener('scroll', handler)
      if (progressTimerRef.current) {
        clearTimeout(progressTimerRef.current)
        progressTimerRef.current = 0
        if (progressValueRef.current) {
          onProgressChange?.(progressValueRef.current.page, progressValueRef.current.ratio)
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, numPages, onProgressChange, onUserScrollRatio])

  // Recompute the rendered window when layout geometry changes without a
  // user scroll (document load, zoom, pane resize).
  useLayoutEffect(() => {
    updateRenderRange()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numPages, mode, scale, containerWidth, ratioTick])

  // Restore the saved reading position once, after the page wrappers have
  // deterministic sizes.
  useLayoutEffect(() => {
    if (restoredPositionRef.current || !numPages || !initialPosition) return
    if (!initialPosition.page && !initialPosition.ratio) {
      restoredPositionRef.current = true
      return
    }
    restoredPositionRef.current = true
    const target = Math.max(1, Math.min(numPages, Math.round(initialPosition.page) || 1))
    if (mode === 'single') {
      setPageNumber(target)
      return
    }
    const scroller = scrollRef.current
    const el = pageRefs.current[target - 1]
    if (!scroller) return
    isProgrammaticScrollRef.current = true
    if (el && target > 1) {
      scroller.scrollTop = el.offsetTop - 8
    } else if (initialPosition.ratio > 0.01) {
      scroller.scrollTop = initialPosition.ratio * Math.max(0, scroller.scrollHeight - scroller.clientHeight)
    }
    updateRenderRange()
    window.setTimeout(() => {
      isProgrammaticScrollRef.current = false
    }, 400)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numPages, mode, initialPosition, ratioTick])

  // Repaint overlays when the annotation set changes (create/delete/sync).
  useEffect(() => {
    repaintRenderedPages()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [annotations])

  // Repaint after React commits new search state; painting reads the ref that
  // only updates on render, so calling it from the search callback directly
  // would paint the previous match set.
  const searchStateKey = `${search.open}|${search.query}|${search.matches.length}|${search.current}`
  useEffect(() => {
    repaintRenderedPages()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchStateKey])

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

  // Capture each page's intrinsic aspect ratio once (from the PDF page
  // dictionaries at load) so the page wrappers can be sized synchronously on
  // every scale change; without stable sizes the layout collapses while
  // react-pdf redraws the canvases asynchronously, which used to yank the
  // scroll position on every zoom step.
  const pageSlotStyle = (
    pageIndex: number,
    extraHeight = 0
  ): React.CSSProperties | undefined => {
    void ratioTick // ratios arrive async; bump forces wraps to re-render sized
    const ratio = pageRatiosRef.current[pageIndex]
    if (!ratio || !containerWidth) return undefined
    const width = containerWidth * scale
    return { width, height: width * ratio + extraHeight }
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

  const renderPage = (index: number, extraHeight: number, withLabel: boolean) => {
    const page = index + 1
    const shouldRender =
      mode === 'single'
        ? page === pageNumber
        : page >= renderRange.start && page <= renderRange.end
    return (
      <div
        key={`page-${page}`}
        className="pdf-page-wrap"
        data-pdf-page={page}
        style={pageSlotStyle(index, extraHeight)}
        ref={(el) => {
          pageRefs.current[index] = el
        }}
      >
        {shouldRender ? (
          <Page
            pageNumber={page}
            scale={scale}
            width={containerWidth}
            renderTextLayer
            renderAnnotationLayer
            onRenderSuccess={() => handlePageRendered(page)}
          />
        ) : (
          <div className="pdf-page-placeholder">
            <span>{page}</span>
          </div>
        )}
        {withLabel && <div className="pdf-page-label muted small">第 {page} 页</div>}
      </div>
    )
  }

  return (
    <div
      className={`pdf-pane ${dragOver ? 'drop-target' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onMouseDownCapture={() => onActivate?.()}
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
          {onCreateAnnotation && !overrideActive && (
            <button
              className="icon-btn"
              title="导出阅读笔记"
              disabled={!annotations.length}
              onClick={() => onExportNotes?.()}
            >
              <BookMarked size={16} />
            </button>
          )}
          <button className="icon-btn" title="搜索（Ctrl+F）" onClick={() => search.openSearch()}>
            <Search size={16} />
          </button>
          {onToggleSync && (
            <button
              className={`icon-btn ${syncEnabled ? 'active' : ''}`}
              title={syncEnabled ? '关闭双栏联动滚动' : '开启双栏联动滚动'}
              onClick={() => onToggleSync()}
            >
              {syncEnabled ? <Link2 size={16} /> : <Link2Off size={16} />}
            </button>
          )}
          <button
            className="icon-btn"
            title="目录"
            onClick={() => setOutlineOpen((v) => !v)}
            disabled={!numPages}
          >
            <List size={16} />
          </button>
          {figures.length > 0 && (
            <button
              className={`icon-btn ${figuresOpen ? 'active' : ''}`}
              title="图表"
              onClick={() => setFiguresOpen((v) => !v)}
            >
              <Images size={16} />
            </button>
          )}
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
        {outlineOpen && (
          <div className="pdf-outline">
            <div className="pdf-outline-heading">
              目录
              {outlineSource === 'generated' && <span>自动生成</span>}
            </div>
            {outlineLoading && <div className="pdf-outline-empty muted">正在生成目录…</div>}
            {!outlineLoading && outlineState.length > 0 && renderOutline(outlineState)}
            {outlineReady && !outlineState.length && (
              <div className="pdf-outline-empty muted">此 PDF 没有书签或可识别的章节文本。</div>
            )}
          </div>
        )}
        {search.open && (
          <div className="pdf-search-bar">
            <input
              autoFocus
              className="pdf-search-input"
              type="text"
              placeholder="在文档中搜索…"
              value={search.query}
              onChange={(event) => search.updateQuery(event.target.value)}
            />
            <span className="pdf-search-count muted small">
              {search.searching ? '搜索中…' : search.matches.length ? `${search.current + 1}/${search.matches.length}` : (search.query ? '无结果' : '')}
            </span>
            <button className="icon-btn" title="上一个 (Shift+Enter)" onClick={search.prev} disabled={!search.matches.length}>
              <ChevronLeft size={14} />
            </button>
            <button className="icon-btn" title="下一个 (Enter)" onClick={search.next} disabled={!search.matches.length}>
              <ChevronRight size={14} />
            </button>
            <button className="icon-btn" title="关闭 (Esc)" onClick={search.closeSearch}>
              <X size={14} />
            </button>
          </div>
        )}
        <div className="pdf-canvas-wrap" ref={scrollRef} onContextMenu={handleTextContextMenu}>
          <Document
            file={fileOpts ?? undefined}
            options={PDF_DOCUMENT_OPTIONS}
            externalLinkTarget="_blank"
            externalLinkRel="noopener noreferrer"
            onLoadSuccess={onDocumentLoadSuccess}
            loading={<div className="muted" style={{ padding: 20 }}>加载中…</div>}
            error={<div className="muted" style={{ padding: 20 }}>无法加载 PDF</div>}
          >
            {numPages > 0 && mode === 'single' && (
              <div
                className="pdf-page-wrap pdf-zoom-stack"
                data-pdf-page={pageNumber}
                style={pageSlotStyle(pageNumber - 1)}
                ref={(el) => {
                  pageRefs.current[pageNumber - 1] = el
                  zoomStackRef.current = el
                }}
              >
                <Page
                  pageNumber={pageNumber}
                  scale={scale}
                  width={containerWidth}
                  renderTextLayer
                  renderAnnotationLayer
                  onRenderSuccess={() => handlePageRendered(pageNumber)}
                />
              </div>
            )}
            {numPages > 0 && mode === 'scroll' && (
              <div className="pdf-scroll-stack" ref={(el) => { zoomStackRef.current = el }}>
                {Array.from({ length: numPages }, (_, i) => renderPage(i, 24, true))}
              </div>
            )}
          </Document>
        </div>
        {figuresOpen && figures.length > 0 && (
          <div className="pdf-figure-strip">
            {figures.map((figure, index) => (
              <button
                key={index}
                className="pdf-figure-card"
                title={figure.caption}
                onClick={() => {
                  if (figure.page != null && figure.page > 0) {
                    gotoPage(figure.page)
                    setFiguresOpen(false)
                  } else if (figure.url) {
                    window.open(figure.url, '_blank', 'noopener,noreferrer')
                  }
                }}
              >
                <img src={figure.url} alt={figure.caption || 'figure'} loading="lazy" />
                <span className="pdf-figure-caption">
                  {figure.caption ? figure.caption.slice(0, 60) : (figure.kind === 'table' ? '表' : '图')}
                  {figure.page != null && figure.page > 0 ? ` · P${figure.page}` : ''}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
      {selectionMenu && (
        <>
          <div className="context-menu-overlay" onClick={() => setSelectionMenu(null)} />
          <div className="context-menu pdf-selection-menu" style={{ top: selectionMenu.y, left: selectionMenu.x }}>
            {selectionMenu.text && (
              <>
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
                {onAskAI && (
                  <button
                    className="context-menu-item"
                    onClick={() => {
                      const selected = selectionMenu
                      setSelectionMenu(null)
                      onAskAI({ selectedText: selected.text, page: selected.page })
                    }}
                  >
                    问 AI
                  </button>
                )}
                {onCreateAnnotation && !overrideActive && (
                  <div className="menu-annotation">
                    <div className="menu-annotation-colors">
                      {ANNOTATION_COLORS.map((color) => (
                        <button
                          key={color}
                          className={`menu-swatch swatch-${color}`}
                          title={`添加${color === 'yellow' ? '黄色' : color === 'green' ? '绿色' : color === 'blue' ? '蓝色' : '粉色'}高亮`}
                          onClick={() => void submitAnnotation(color)}
                        />
                      ))}
                    </div>
                    <input
                      className="menu-annotation-note"
                      type="text"
                      placeholder="备注（可选，Enter 保存黄色高亮）"
                      value={noteDraft}
                      onChange={(event) => setNoteDraft(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          void submitAnnotation('yellow')
                        }
                      }}
                    />
                  </div>
                )}
              </>
            )}
            {selectionMenu.annotationId && onDeleteAnnotation && (
              <button
                className="context-menu-item"
                onClick={() => {
                  const id = selectionMenu.annotationId
                  setSelectionMenu(null)
                  if (id) void onDeleteAnnotation(id)
                }}
              >
                删除此批注
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
                清除对照高亮
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
})
