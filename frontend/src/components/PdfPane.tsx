import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { PDF_DOCUMENT_OPTIONS } from '../lib/pdfDocumentOptions'
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

pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

export type PdfPaneHandle = {
  locateAndHighlight: (payload: { text: string; positionRatio: number }) => Promise<void>
}

type OutlineItem = {
  title: string
  pageIndex: number | null
  items: OutlineItem[]
}

type TextLine = {
  text: string
  fontSize: number
}

type FlatHeading = {
  title: string
  pageIndex: number
  level: number
}

type ViewMode = 'scroll' | 'single'

function median(values: number[]): number {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function headingFromLine(
  line: TextLine,
  bodySize: number,
  allowLetteredAppendix: boolean,
): { title: string; level: number } | null {
  const title = line.text.replace(/\s+/g, ' ').trim()
  if (title.length < 2 || title.length > 180) return null

  const numbered = title.match(/^(\d+(?:\.\d+)*)(?:\.)?\s+([A-Z\u3400-\u9fff].*)$/)
  if (numbered && line.fontSize >= Math.max(8, bodySize * 0.9)) {
    const headingText = numbered[2].trim()
    if (/[.!?]\s+[A-Z\u3400-\u9fff]/.test(headingText) || /[.!?]$/.test(headingText)) return null
    return { title, level: numbered[1].split('.').length }
  }

  const appendix = allowLetteredAppendix && (
    title.match(/^([A-H])\.(\d+(?:\.\d+)*)\s+([A-Z\u3400-\u9fff].*)$/)
      || title.match(/^([A-H])(?:\.)?\s+([A-Z\u3400-\u9fff].*)$/)
  )
  if (appendix && line.fontSize >= Math.max(8, bodySize * 0.9)) {
    const appendixLevel = appendix.length === 4 ? appendix[2].split('.').length + 1 : 1
    return { title, level: appendixLevel }
  }

  const named = /^(?:Abstract|Introduction|Conclusion|Conclusions|References|Acknowledgements?|Appendix(?:\s+[A-Z0-9]+)?|摘要|引言|结论|参考文献|致谢|附录(?:\s*[A-Z0-9一二三四五六七八九十]+)?)(?:\s|$|[:：])/i
  if (named.test(title) && line.fontSize >= Math.max(8, bodySize * 0.9)) {
    return { title, level: 1 }
  }
  return null
}

function nestHeadings(headings: FlatHeading[]): OutlineItem[] {
  const roots: OutlineItem[] = []
  const stack: Array<{ level: number; item: OutlineItem }> = []
  for (const heading of headings) {
    const item: OutlineItem = { title: heading.title, pageIndex: heading.pageIndex, items: [] }
    while (stack.length && stack[stack.length - 1].level >= heading.level) stack.pop()
    if (stack.length) stack[stack.length - 1].item.items.push(item)
    else roots.push(item)
    stack.push({ level: heading.level, item })
  }
  return roots
}

async function buildSyntheticOutline(doc: any): Promise<OutlineItem[]> {
  const headings: FlatHeading[] = []
  let afterReferences = false
  let finished = false
  for (let pageIndex = 0; pageIndex < doc.numPages; pageIndex += 1) {
    if (finished) break
    const page = await doc.getPage(pageIndex + 1)
    const content = await page.getTextContent()
    const grouped = new Map<number, Array<{ text: string; x: number; width: number; size: number }>>()
    const fontSizes: number[] = []
    for (const item of content.items || []) {
      const text = String(item.str || '').trim()
      if (!text) continue
      const transform = item.transform || []
      const x = Number(transform[4] || 0)
      const y = Number(transform[5] || 0)
      const size = Math.max(Number(item.height || 0), Math.hypot(Number(transform[0] || 0), Number(transform[1] || 0)))
      const width = Math.max(0, Number(item.width || 0))
      const key = Math.round(y / 2) * 2
      const row = grouped.get(key) || []
      row.push({ text, x, width, size })
      grouped.set(key, row)
      if (size > 0) fontSizes.push(size)
    }
    const lines = Array.from(grouped.values()).flatMap((row) => {
      const clusters: typeof row[] = []
      for (const part of row.sort((a, b) => a.x - b.x)) {
        const cluster = clusters[clusters.length - 1]
        const previous = cluster?.[cluster.length - 1]
        const previousEnd = previous ? previous.x + previous.width : 0
        if (!cluster || part.x - previousEnd > Math.max(40, part.size * 4)) clusters.push([part])
        else cluster.push(part)
      }
      return clusters.map((cluster) => ({
        text: cluster.map((part) => part.text).join(' '),
        fontSize: Math.max(...cluster.map((part) => part.size)),
      }))
    })
    const bodySize = median(fontSizes) || 10
    for (const line of lines) {
      if (/^NeurIPS Paper Checklist$/i.test(line.text.trim())) {
        finished = true
        break
      }
      const heading = headingFromLine(line, bodySize, afterReferences)
      if (!heading) continue
      if (afterReferences && /^\d/.test(heading.title)) continue
      const previous = headings[headings.length - 1]
      if (previous && previous.title === heading.title && previous.pageIndex === pageIndex) continue
      headings.push({ ...heading, pageIndex })
      if (/^(?:References|参考文献)(?:\s|$|[:：])/i.test(heading.title)) afterReferences = true
    }
  }
  return nestHeadings(headings)
}

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
  const zoomStackRef = useRef<HTMLDivElement | null>(null)
  const pageRatiosRef = useRef<Array<number | null>>([])
  const pendingAnchorRef = useRef<{
    stackLayoutLeft: number
    stackLayoutTop: number
    originX: number
    originY: number
    localX: number
    localY: number
    ratio: number
  } | null>(null)
  const gestureRef = useRef({
    active: false,
    base: 1,
    target: 1,
    display: 1,
    stackLayoutLeft: 0,
    stackLayoutTop: 0,
    originX: 0,
    originY: 0,
    localX: 0,
    localY: 0,
    raf: 0,
    commitTimer: 0 as ReturnType<typeof setTimeout> | 0,
    touchStart: null as { distance: number; scale: number } | null,
    gestureStartScale: 1
  })
  const [numPages, setNumPages] = useState(0)
  const [ratioTick, setRatioTick] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [scale, setScale] = useState(1.0)
  const [zoomInput, setZoomInput] = useState('100')
  const [containerWidth, setContainerWidth] = useState<number | undefined>(undefined)
  const [outline, setOutline] = useState<OutlineItem[]>([])
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
  } | null>(null)

  const effectiveUrl = overrideUrl || pdfUrl
  const effectiveTitle = overrideUrl ? (overrideTitle || '已覆盖') : title

  useEffect(() => {
    setPageNumber(1)
    setOutline([])
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
    const gesture = gestureRef.current
    gesture.active = false
    gesture.touchStart = null
    if (gesture.raf) cancelAnimationFrame(gesture.raf)
    gesture.raf = 0
    if (gesture.commitTimer) clearTimeout(gesture.commitTimer)
    gesture.commitTimer = 0
    if (zoomStackRef.current) {
      zoomStackRef.current.style.transform = ''
      zoomStackRef.current.style.willChange = ''
    }
    pendingAnchorRef.current = null
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
  }, [scale])

  useEffect(() => {
    const scroller = scrollRef.current
    if (!scroller || !effectiveUrl) return

    const clampScale = (value: number) => Math.max(0.4, Math.min(3, value))
    const gesture = gestureRef.current

    const beginGesture = (clientX: number, clientY: number) => {
      const stack = zoomStackRef.current
      if (!stack) return
      if (!gesture.active) {
        const scrollerRect = scroller.getBoundingClientRect()
        const stackRect = stack.getBoundingClientRect()
        gesture.active = true
        gesture.base = scaleRef.current
        gesture.display = scaleRef.current
        gesture.target = scaleRef.current
        gesture.localX = clientX - scrollerRect.left
        gesture.localY = clientY - scrollerRect.top
        // Anchor in the stack's own (untransformed) coordinate space; the
        // stack's layout offset inside the scroller's scroll content.
        gesture.originX = clientX - stackRect.left
        gesture.originY = clientY - stackRect.top
        gesture.stackLayoutLeft = stackRect.left - scrollerRect.left + scroller.scrollLeft
        gesture.stackLayoutTop = stackRect.top - scrollerRect.top + scroller.scrollTop
        stack.style.willChange = 'transform'
      }
      if (gesture.commitTimer) clearTimeout(gesture.commitTimer)
    }

    const applyTransformFrame = () => {
      gesture.raf = 0
      const stack = zoomStackRef.current
      if (!gesture.active || !stack) return
      // Exponential smoothing turns discrete (possibly coarse) input events
      // into continuous visual motion.
      gesture.display += (gesture.target - gesture.display) * 0.35
      if (Math.abs(gesture.target - gesture.display) < 0.0005) gesture.display = gesture.target
      const k = gesture.display / gesture.base
      stack.style.transformOrigin = `${gesture.originX}px ${gesture.originY}px`
      stack.style.transform = `scale(${k})`
      // Keep the anchor point glued under the cursor while the layout (and
      // therefore the scroll range) is still at the base scale.
      scroller.scrollLeft = gesture.stackLayoutLeft + gesture.originX * k - gesture.localX
      scroller.scrollTop = gesture.stackLayoutTop + gesture.originY * k - gesture.localY
      if (gesture.display !== gesture.target) {
        gesture.raf = requestAnimationFrame(applyTransformFrame)
      }
    }

    const commitGesture = () => {
      if (gesture.commitTimer) {
        clearTimeout(gesture.commitTimer)
        gesture.commitTimer = 0
      }
      if (!gesture.active) return
      const stack = zoomStackRef.current
      const finalScale = clampScale(Math.round(gesture.target * 100) / 100)
      const ratio = finalScale / gesture.base
      gesture.active = false
      if (gesture.raf) cancelAnimationFrame(gesture.raf)
      gesture.raf = 0
      if (stack) {
        stack.style.transform = ''
        stack.style.willChange = ''
      }
      // Layout catches up when React re-renders with the new scale; once it
      // has, re-anchor the scroll so the gesture focal point stays put.
      pendingAnchorRef.current = {
        stackLayoutLeft: gesture.stackLayoutLeft,
        stackLayoutTop: gesture.stackLayoutTop,
        originX: gesture.originX,
        originY: gesture.originY,
        localX: gesture.localX,
        localY: gesture.localY,
        ratio
      }
      scaleRef.current = finalScale
      setScale(finalScale)
    }

    const scheduleCommit = () => {
      if (gesture.commitTimer) clearTimeout(gesture.commitTimer)
      gesture.commitTimer = setTimeout(commitGesture, 220)
    }

    const updateTarget = (nextScale: number, clientX: number, clientY: number) => {
      beginGesture(clientX, clientY)
      if (!gesture.active) return
      gesture.target = clampScale(nextScale)
      if (!gesture.raf) gesture.raf = requestAnimationFrame(applyTransformFrame)
      scheduleCommit()
    }

    const onWheel = (event: WheelEvent) => {
      // Desktop trackpad pinch gestures are exposed as ctrl+wheel by
      // Chromium/WebView2; Safari/WKWebView additionally emits gesturechange.
      if (!event.ctrlKey) return
      event.preventDefault()
      event.stopPropagation()
      let dy = event.deltaY
      if (event.deltaMode === 1) dy *= 33 // lines (Safari keyboard)
      else if (event.deltaMode === 2) dy *= scroller.clientHeight // pages
      // Normalize across platforms: Windows precision touchpads emit few,
      // coarse deltas (±53..±120) while macOS emits many tiny ones (±1..±3).
      // Clamp the per-event factor so a coarse Windows notch cannot jump
      // 2-3x in a single event, then let the rAF lerp smooth it out.
      const factor = Math.exp(-dy * 0.01)
      const clamped = Math.min(1.12, Math.max(1 / 1.12, factor))
      updateTarget((gesture.active ? gesture.target : scaleRef.current) * clamped, event.clientX, event.clientY)
    }

    const distance = (touches: TouchList) => {
      const dx = touches[0].clientX - touches[1].clientX
      const dy = touches[0].clientY - touches[1].clientY
      return Math.hypot(dx, dy)
    }
    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 2) return
      gesture.touchStart = { distance: distance(event.touches), scale: gesture.active ? gesture.target : scaleRef.current }
    }
    const onTouchMove = (event: TouchEvent) => {
      if (event.touches.length !== 2 || !gesture.touchStart) return
      event.preventDefault()
      event.stopPropagation()
      const midpointX = (event.touches[0].clientX + event.touches[1].clientX) / 2
      const midpointY = (event.touches[0].clientY + event.touches[1].clientY) / 2
      const ratio = distance(event.touches) / Math.max(1, gesture.touchStart.distance)
      updateTarget(gesture.touchStart.scale * ratio, midpointX, midpointY)
    }
    const onTouchEnd = () => {
      gesture.touchStart = null
      if (gesture.active) commitGesture()
    }

    // WebKit (Safari / WKWebView on macOS) reports trackpad pinch via
    // non-standard gesture events instead of ctrl+wheel.
    const onGestureStart = (event: any) => {
      event.preventDefault()
      gesture.gestureStartScale = gesture.active ? gesture.target : scaleRef.current
    }
    const onGestureChange = (event: any) => {
      event.preventDefault()
      if (!event.scale) return
      updateTarget(gesture.gestureStartScale * event.scale, event.clientX, event.clientY)
    }
    const onGestureEnd = (event: any) => {
      event.preventDefault()
      if (gesture.active) commitGesture()
    }

    scroller.addEventListener('wheel', onWheel, { passive: false })
    scroller.addEventListener('touchstart', onTouchStart, { passive: true })
    scroller.addEventListener('touchmove', onTouchMove, { passive: false })
    scroller.addEventListener('touchend', onTouchEnd)
    scroller.addEventListener('touchcancel', onTouchEnd)
    scroller.addEventListener('gesturestart', onGestureStart as EventListener)
    scroller.addEventListener('gesturechange', onGestureChange as EventListener)
    scroller.addEventListener('gestureend', onGestureEnd as EventListener)
    return () => {
      scroller.removeEventListener('wheel', onWheel)
      scroller.removeEventListener('touchstart', onTouchStart)
      scroller.removeEventListener('touchmove', onTouchMove)
      scroller.removeEventListener('touchend', onTouchEnd)
      scroller.removeEventListener('touchcancel', onTouchEnd)
      scroller.removeEventListener('gesturestart', onGestureStart as EventListener)
      scroller.removeEventListener('gesturechange', onGestureChange as EventListener)
      scroller.removeEventListener('gestureend', onGestureEnd as EventListener)
      if (gesture.raf) cancelAnimationFrame(gesture.raf)
      gesture.raf = 0
      if (gesture.commitTimer) clearTimeout(gesture.commitTimer)
      gesture.commitTimer = 0
      gesture.active = false
    }
  }, [effectiveUrl])

  // After a zoom commit re-renders the pages at the new scale, restore the
  // scroll position so the gesture anchor stays under the cursor.
  useLayoutEffect(() => {
    const anchor = pendingAnchorRef.current
    const scroller = scrollRef.current
    if (!anchor || !scroller) return
    pendingAnchorRef.current = null
    scroller.scrollLeft = anchor.stackLayoutLeft + anchor.originX * anchor.ratio - anchor.localX
    scroller.scrollTop = anchor.stackLayoutTop + anchor.originY * anchor.ratio - anchor.localY
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
      const raw = await doc.getOutline()
      if (raw?.length) {
        const built = await Promise.all(raw.map((item: any) => mapOutlineItem(doc, item)))
        if (pdfDocumentRef.current === doc) {
          setOutline(built)
          setOutlineSource('native')
        }
      } else {
        const built = await buildSyntheticOutline(doc)
        if (pdfDocumentRef.current === doc) {
          setOutline(built)
          setOutlineSource(built.length ? 'generated' : null)
        }
      }
    } catch {
      if (pdfDocumentRef.current === doc) {
        setOutline([])
        setOutlineSource(null)
      }
    } finally {
      if (pdfDocumentRef.current === doc) {
        setOutlineLoading(false)
        setOutlineReady(true)
      }
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
            disabled={!numPages}
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
        {outlineOpen && (
          <div className="pdf-outline">
            <div className="pdf-outline-heading">
              目录
              {outlineSource === 'generated' && <span>自动生成</span>}
            </div>
            {outlineLoading && <div className="pdf-outline-empty muted">正在生成目录…</div>}
            {!outlineLoading && outline.length > 0 && renderOutline(outline)}
            {outlineReady && !outline.length && (
              <div className="pdf-outline-empty muted">此 PDF 没有书签或可识别的章节文本。</div>
            )}
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
                />
              </div>
            )}
            {numPages > 0 && mode === 'scroll' && (
              <div className="pdf-scroll-stack" ref={(el) => { zoomStackRef.current = el }}>
                {Array.from({ length: numPages }, (_, i) => (
                  <div
                    key={`page-${i + 1}`}
                    className="pdf-page-wrap"
                    data-pdf-page={i + 1}
                    style={pageSlotStyle(i, 24)}
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
