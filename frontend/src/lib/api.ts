export type UploadResult = { document_id: string; status: string }

export type ArtifactItem = {
  name: string
  kind: string
  path: string
  url?: string | null
}

export type ReferenceItem = {
  index: number
  text: string
}

export type DocumentStatus = {
  document_id: string
  status: string
  source_type: string
  source_filename: string
  original_pdf_url?: string | null
  translated_pdf_url?: string | null
  artifacts: ArtifactItem[]
  references: ReferenceItem[]
  logs: string[]
}

export type DocumentSummary = {
  document_id: string
  status: string
  source_type: string
  source_filename: string
  size_bytes: number
  created_at?: string | null
  has_translated_pdf: boolean
}

const BACKEND = (import.meta as any).env?.VITE_BACKEND_URL || 'http://localhost:8000'

export async function uploadFile(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BACKEND}/api/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getDocumentStatus(documentId: string): Promise<DocumentStatus> {
  const res = await fetch(`${BACKEND}/api/document/${documentId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch(`${BACKEND}/api/documents`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function sendChat(payload: {
  document_id: string
  message: string
  override_api_key?: string
  override_base_url?: string
  override_model?: string
}): Promise<{ answer: string }> {
  const res = await fetch(`${BACKEND}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function makeDataUrl(path?: string | null): string {
  if (!path) return ''
  return `${BACKEND}${path}`
}
