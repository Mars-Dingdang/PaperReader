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

export type StageItem = {
  key: string
  label: string
  weight: number
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  started_at?: number | null
  ended_at?: number | null
  duration_ms?: number | null
}

export type ReviewProposalItem = {
  page_index: number
  issues: string[]
  original_md: string
  proposed_md: string
  image_url?: string | null
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
  progress: number
  current_stage?: string | null
  current_stage_label?: string | null
  eta_seconds?: number | null
  stages: StageItem[]
  pending_reviews: ReviewProposalItem[]
  last_compile_warning?: string | null
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

export type UploadOptions = {
  visionCheckEnabled?: boolean
  visionCheckMode?: 'auto' | 'manual'
}

export async function uploadFile(file: File, options: UploadOptions = {}): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('vision_check_enabled', String(options.visionCheckEnabled ?? true))
  form.append('vision_check_mode', options.visionCheckMode ?? 'auto')
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

// ============ Project (Phase B) ============
export type ProjectFileItem = { relative_path: string; size: number; kind: string }
export type ProjectDetail = {
  project_id: string
  name: string
  main_tex: string | null
  files: ProjectFileItem[]
  main_candidates: string[]
}

export async function createProject(name?: string): Promise<{ project_id: string; name: string }> {
  const res = await fetch(`${BACKEND}/api/project`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(name ? { name } : {})
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const res = await fetch(`${BACKEND}/api/project/${projectId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadProjectFile(
  projectId: string,
  file: File,
  relativePath?: string
): Promise<ProjectDetail> {
  const form = new FormData()
  form.append('file', file)
  form.append('relative_path', relativePath || file.name)
  const res = await fetch(`${BACKEND}/api/project/${projectId}/files`, {
    method: 'POST',
    body: form
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteProjectFiles(projectId: string, relativePaths: string[]): Promise<ProjectDetail> {
  const res = await fetch(`${BACKEND}/api/project/${projectId}/delete-files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ relative_paths: relativePaths })
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function buildProject(
  projectId: string,
  mainTex: string,
  options: UploadOptions = {}
): Promise<UploadResult> {
  const res = await fetch(`${BACKEND}/api/project/${projectId}/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      main_tex: mainTex,
      vision_check_enabled: options.visionCheckEnabled ?? true,
      vision_check_mode: options.visionCheckMode ?? 'auto'
    })
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ============ Review (Phase D) ============
export async function postReviewDecision(
  documentId: string,
  accept: boolean,
  edits?: string
): Promise<void> {
  const res = await fetch(`${BACKEND}/api/document/${documentId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accept, edits })
  })
  if (!res.ok) throw new Error(await res.text())
}

// ============ Manual TeX recompile ============
export type RecompileResult = {
  ok: boolean
  pdf_url?: string | null
  warning?: string | null
  error?: string | null
}

export async function getDocumentTex(documentId: string): Promise<string> {
  const res = await fetch(`${BACKEND}/api/document/${documentId}/tex`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  return (data.tex_content as string) || ''
}

export async function recompileDocument(
  documentId: string,
  texContent: string
): Promise<RecompileResult> {
  const res = await fetch(`${BACKEND}/api/document/${documentId}/tex`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tex_content: texContent })
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
