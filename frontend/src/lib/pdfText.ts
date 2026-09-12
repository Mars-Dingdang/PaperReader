// Shared text-layer helpers.  All matching happens on "normalized" text:
// lowercased with every non-alphanumeric/CJK character stripped, so PDF
// extraction quirks (line breaks, hyphenation, spacing) do not break matches.

export function normalized(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '')
}

export type SpanIndex = {
  spans: Array<{ el: HTMLElement; start: number; end: number }>
  text: string
}

export function buildSpanIndex(pageEl: HTMLElement): SpanIndex | null {
  const spans = Array.from(
    pageEl.querySelectorAll<HTMLElement>('.react-pdf__Page__textContent span')
  )
  if (!spans.length) return null
  let text = ''
  const entries = spans.map((el) => {
    const start = text.length
    text += normalized(el.textContent || '')
    return { el, start, end: text.length }
  })
  return { spans: entries, text }
}

export function paintRange(index: SpanIndex, start: number, end: number, classNames: string): void {
  for (const entry of index.spans) {
    if (entry.end <= start || entry.start >= end) continue
    for (const cls of classNames.split(' ')) entry.el.classList.add(cls)
  }
}

export type Match = { page: number; start: number; length: number }

// Largest prefix of `target` (in 120/60/24-char steps) that appears in
// `pageText`.  Mirrors the granularity of the locate pipeline.
export function prefixMatchScore(pageText: string, target: string): number {
  if (!pageText || !target) return 0
  for (const len of [120, 60, 24]) {
    const needle = target.slice(0, len)
    if (needle.length >= 12 && pageText.includes(needle)) return len
  }
  return 0
}

export function locateNeedle(index: SpanIndex, target: string): { start: number; length: number } | null {
  const needle = normalized(target)
  if (!needle) return null
  for (const len of [140, 60, 24]) {
    const prefix = needle.slice(0, len)
    if (prefix.length < 6) break
    const at = index.text.indexOf(prefix)
    if (at >= 0) return { start: at, length: Math.min(needle.length, len) }
  }
  return null
}
