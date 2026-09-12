export type OutlineItem = {
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

export async function buildSyntheticOutline(doc: any): Promise<OutlineItem[]> {
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
