import { useCallback, useEffect, useRef } from 'react'
import { normalized } from '../lib/pdfText'

type Options = {
  docRef: React.MutableRefObject<any>
  activeKey: string
}

// Lazily extracts and caches the normalized text of each page from the
// pdf.js document.  One source of truth for locate, search, and any other
// whole-document text matching, so repeated lookups do not re-hit the worker.
export function usePageText({ docRef, activeKey }: Options) {
  const cacheRef = useRef<Map<number, string>>(new Map())
  const pendingRef = useRef<Map<number, Promise<string>>>(new Map())

  useEffect(() => {
    cacheRef.current.clear()
    pendingRef.current.clear()
  }, [activeKey])

  const getPageText = useCallback(
    (page: number): Promise<string> => {
      const cached = cacheRef.current.get(page)
      if (cached !== undefined) return Promise.resolve(cached)
      const pending = pendingRef.current.get(page)
      if (pending) return pending
      const doc = docRef.current
      if (!doc) return Promise.resolve('')
      const task = doc
        .getPage(page)
        .then((pdfPage: any) => pdfPage.getTextContent())
        .then((content: any) => {
          const text = normalized(
            (content.items || []).map((item: any) => item.str || '').join(' ')
          )
          cacheRef.current.set(page, text)
          pendingRef.current.delete(page)
          return text
        })
        .catch(() => {
          pendingRef.current.delete(page)
          return ''
        })
      pendingRef.current.set(page, task)
      return task
    },
    [docRef]
  )

  return { getPageText }
}
