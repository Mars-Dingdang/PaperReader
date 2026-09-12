import { useEffect, useLayoutEffect, useRef } from 'react'

type PendingAnchor = {
  stackLayoutLeft: number
  stackLayoutTop: number
  originX: number
  originY: number
  localX: number
  localY: number
  ratio: number
}

type Options = {
  scrollerRef: React.RefObject<HTMLDivElement | null>
  zoomStackRef: React.MutableRefObject<HTMLDivElement | null>
  scaleRef: React.MutableRefObject<number>
  scale: number
  setScale: (next: number) => void
  activeKey: string
}

// Trackpad pinch / ctrl+wheel zoom.  The gesture renders a live transform on
// the zoom stack and commits the new React scale once the gesture settles,
// re-anchoring the scroll position so the focal point stays under the cursor.
export function usePdfZoom({ scrollerRef, zoomStackRef, scaleRef, scale, setScale, activeKey }: Options) {
  const pendingAnchorRef = useRef<PendingAnchor | null>(null)
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

  // Reset internal state when the document changes.
  useEffect(() => {
    const gesture = gestureRef.current
    gesture.active = false
    gesture.touchStart = null
    if (gesture.raf) cancelAnimationFrame(gesture.raf)
    gesture.raf = 0
    if (gesture.commitTimer) clearTimeout(gesture.commitTimer)
    gesture.commitTimer = 0
    pendingAnchorRef.current = null
  }, [activeKey])

  useEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller || !activeKey) return

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
  }, [activeKey, scrollerRef, scaleRef, setScale, zoomStackRef])

  // After a zoom commit re-renders the pages at the new scale, restore the
  // scroll position so the gesture anchor stays under the cursor.
  useLayoutEffect(() => {
    const anchor = pendingAnchorRef.current
    const scroller = scrollerRef.current
    if (!anchor || !scroller) return
    pendingAnchorRef.current = null
    scroller.scrollLeft = anchor.stackLayoutLeft + anchor.originX * anchor.ratio - anchor.localX
    scroller.scrollTop = anchor.stackLayoutTop + anchor.originY * anchor.ratio - anchor.localY
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scale])
}
