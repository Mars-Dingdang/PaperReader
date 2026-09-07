import { useEffect, useRef, useState } from 'react'
import { Document, Page } from 'react-pdf'
import { makeDataUrl } from '../lib/api'

type Props = {
  url: string
  kind: string
  name: string
  anchorRect: DOMRect
}

const TEXT_KINDS = new Set(['translated_tex', 'source_tex', 'mineru_output'])
const IMAGE_EXT = /\.(png|jpe?g|gif|svg|webp)$/i
const PDF_EXT = /\.pdf(\?|$)/i

function classify(kind: string, name: string): 'pdf' | 'image' | 'text' | 'unknown' {
  if (kind.includes('pdf') || PDF_EXT.test(name)) return 'pdf'
  if (IMAGE_EXT.test(name)) return 'image'
  if (TEXT_KINDS.has(kind) || /\.(tex|md|txt|log|bib)$/i.test(name)) return 'text'
  return 'unknown'
}

const TEXT_CACHE = new Map<string, string>()

export function ArtifactPreviewTip({ url, kind, name, anchorRect }: Props) {
  const [text, setText] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement | null>(null)
  const fullUrl = makeDataUrl(url)
  const type = classify(kind, name)

  useEffect(() => {
    if (type !== 'text') return
    if (TEXT_CACHE.has(fullUrl)) {
      setText(TEXT_CACHE.get(fullUrl) || '')
      return
    }
    let cancelled = false
    fetch(fullUrl, { credentials: 'include' })
      .then((r) => (r.ok ? r.text() : ''))
      .then((t) => {
        const head = t.split('\n').slice(0, 60).join('\n')
        TEXT_CACHE.set(fullUrl, head)
        if (!cancelled) setText(head)
      })
      .catch(() => {
        if (!cancelled) setText('（无法加载预览）')
      })
    return () => {
      cancelled = true
    }
  }, [fullUrl, type])

  // position to right of anchor; clamp within viewport
  const TIP_W = 240
  const TIP_H = 280
  let left = anchorRect.right + 8
  let top = anchorRect.top
  if (left + TIP_W > window.innerWidth - 8) left = anchorRect.left - TIP_W - 8
  if (top + TIP_H > window.innerHeight - 8) top = window.innerHeight - TIP_H - 8
  if (top < 8) top = 8

  return (
    <div
      ref={ref}
      className="artifact-tip"
      style={{ left, top, width: TIP_W }}
    >
      <div className="artifact-tip-header small muted">{name}</div>
      <div className="artifact-tip-body">
        {type === 'pdf' && (
          <Document file={{ url: fullUrl }} loading={<div className="muted small">加载中…</div>}
            error={<div className="muted small">无法预览</div>}
          >
            <Page pageNumber={1} width={TIP_W - 16} renderTextLayer={false} renderAnnotationLayer={false} />
          </Document>
        )}
        {type === 'image' && (
          // eslint-disable-next-line jsx-a11y/alt-text
          <img src={fullUrl} style={{ width: '100%', display: 'block' }} />
        )}
        {type === 'text' && (
          <pre className="artifact-tip-pre">{text ?? '加载中…'}</pre>
        )}
        {type === 'unknown' && <div className="muted small">不支持预览</div>}
      </div>
    </div>
  )
}
