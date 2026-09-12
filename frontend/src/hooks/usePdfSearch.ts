import { useCallback, useEffect, useRef, useState } from 'react'
import { normalized, type Match } from '../lib/pdfText'

type Options = {
  getPageText: (page: number) => Promise<string>
  numPages: number
  goto: (page: number) => void
  onRepaint: () => void
}

const MAX_MATCHES = 500

// Whole-document find (Ctrl+F).  Matches are computed over the cached page
// texts and painted by the pane's overlay pass; navigation jumps to the page
// holding the current match.
export function usePdfSearch({ getPageText, numPages, goto, onRepaint }: Options) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Match[]>([])
  const [current, setCurrent] = useState(0)
  const [searching, setSearching] = useState(false)
  const stateRef = useRef({ open, query, matches, current })
  stateRef.current = { open, query, matches, current }

  const run = useCallback(
    async (rawQuery: string) => {
      const needle = normalized(rawQuery)
      if (!needle || !numPages) {
        setMatches([])
        setCurrent(0)
        onRepaint()
        return
      }
      setSearching(true)
      try {
        const found: Match[] = []
        for (let page = 1; page <= numPages && found.length < MAX_MATCHES; page += 1) {
          const text = await getPageText(page)
          if (!text) continue
          let at = text.indexOf(needle)
          while (at >= 0 && found.length < MAX_MATCHES) {
            found.push({ page, start: at, length: needle.length })
            at = text.indexOf(needle, at + 1)
          }
        }
        setMatches(found)
        setCurrent(0)
        onRepaint()
        if (found.length) goto(found[0].page)
      } finally {
        setSearching(false)
      }
    },
    [getPageText, goto, numPages, onRepaint]
  )

  const openSearch = useCallback(() => {
    setOpen(true)
  }, [])

  const closeSearch = useCallback(() => {
    setOpen(false)
    setQuery('')
    setMatches([])
    setCurrent(0)
    setSearching(false)
    onRepaint()
  }, [onRepaint])

  const step = useCallback(
    (delta: number) => {
      const { matches: list, current: index } = stateRef.current
      if (!list.length) return
      const nextIndex = (index + delta + list.length) % list.length
      setCurrent(nextIndex)
      goto(list[nextIndex].page)
      onRepaint()
    },
    [goto, onRepaint]
  )

  const updateQuery = useCallback(
    (value: string) => {
      setQuery(value)
      if (!value.trim()) {
        setMatches([])
        setCurrent(0)
        onRepaint()
        return
      }
      void run(value)
    },
    [onRepaint, run]
  )

  // Escape closes; the browser find is suppressed by the ReaderPage-level
  // Ctrl/Cmd+F handler, so no extra interception here.
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        closeSearch()
      } else if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        step(1)
      } else if (event.key === 'Enter' && event.shiftKey) {
        event.preventDefault()
        step(-1)
      }
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [closeSearch, open, step])

  return {
    open,
    query,
    matches,
    current,
    searching,
    stateRef,
    openSearch,
    closeSearch,
    updateQuery,
    next: () => step(1),
    prev: () => step(-1),
  }
}
