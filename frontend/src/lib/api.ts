import type { OutlineItem } from './pdfOutline'

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

export type FailureItem = {
  stage: string
  message: string
  retryable: boolean
  chunk?: number | null
  retry_count: number
}

export type LatexRecoveryItem = {
  status: 'analyzing' | 'repairing' | 'recompiling' | 'succeeded' | 'failed'
  diagnosis?: string | null
  repairs: Array<{
    start_line?: number
    end_line?: number
    original?: string
    replacement?: string
    reason?: string
    round?: number
  }>
  rounds: number
  last_error?: string | null
}

export type DocumentStatus = {
  document_id: string
  status: string
  source_type: string
  source_filename: string
  updated_at?: string | null
  last_opened_at?: string | null
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
  failure?: FailureItem | null
  latex_recovery?: LatexRecoveryItem | null
  last_read_page: number
  last_read_ratio: number
}

export type DocumentSummary = {
  document_id: string
  status: string
  source_type: string
  source_filename: string
  size_bytes: number
  created_at?: string | null
  updated_at?: string | null
  last_opened_at?: string | null
  has_translated_pdf: boolean
  title: string
  year: string
}

export type AnnotationItem = {
  id: string
  page: number
  quote: string
  color: string
  note: string
  position_ratio: number
  created_at: string
}

export type FigureItem = {
  kind: string
  caption: string
  page: number | null
  url: string
}

export type DocumentStructure = {
  outline: OutlineItem[]
  figures: FigureItem[]
}

export type LibrarySearchHit = {
  document_id: string
  document_title: string
  side: 'original' | 'translated'
  snippet: string
  position_ratio: number
}

export type SourceRefItem = {
  label: string
  title: string
  content: string
  document_id?: string | null
  position_ratio?: number | null
}

export type UserSettings = {
  api_key_configured: boolean
  base_url: string
  model: string
  pdf_parser: 'local' | 'mineru'
  mineru_api_key_configured: boolean
  mineru_base_url: string
  mineru_model_version: string
  mineru_language: string
  mineru_enable_formula: boolean
  mineru_enable_table: boolean
  mineru_is_ocr: boolean
  vision_model: string
  theme: 'light' | 'dark'
  vision_enabled: boolean
  vision_mode: 'auto' | 'manual'
  favorites: string[]
}

export type ProviderSettingsDraft = {
  api_key: string
  clear_api_key?: boolean
  base_url: string
  model: string
  pdf_parser: 'local' | 'mineru'
  mineru_api_key: string
  clear_mineru_api_key?: boolean
  mineru_base_url: string
  mineru_model_version: string
  mineru_language: string
  mineru_enable_formula: boolean
  mineru_enable_table: boolean
  mineru_is_ocr: boolean
  vision_model: string
}

export type SetupStatus = {
  required: boolean
  desktop: boolean
  defaults?: Omit<ProviderSettingsDraft, 'api_key' | 'mineru_api_key'>
}

export type AuthUser = {
  id: number
  username: string
  avatar_url?: string | null
  created_at: string
  updated_at: string
  last_login_at?: string | null
  settings: UserSettings
}

export type ProjectFileItem = { relative_path: string; size: number; kind: string }
export type ProjectDetail = {
  project_id: string
  name: string
  main_tex: string | null
  files: ProjectFileItem[]
  main_candidates: string[]
}

export type LintIssue = {
  line: number | null
  message: string
}

export type MissingChar = {
  char: string
  codepoint: string
  count: number
  suggest: string | null
}

export type RecompileResult = {
  ok: boolean
  pdf_url?: string | null
  warning?: string | null
  error?: string | null
  issues?: LintIssue[]
  missing_chars?: MissingChar[]
}

export type DocumentTex = {
  tex_content: string
  path: string
}

export type ChatMessage = {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export type ChatSession = {
  session_id: string
  scope: 'document' | 'library'
  document_ids: string[]
  title: string
  created_at: string
  updated_at: string
  messages: ChatMessage[]
}

// Production (including the portable app) uses the page's origin so session
// cookies work for localhost, 127.0.0.1, and reverse-proxy deployments alike.
const BACKEND = (import.meta.env.VITE_BACKEND_URL || (
  import.meta.env.DEV ? 'http://localhost:8000' : ''
)).replace(/\/$/, '')

export class ApiError extends Error {
  status?: number
  code?: string
}

async function apiFetch(path: string, init: RequestInit = {}, expectJson = true) {
  const res = await fetch(`${BACKEND}${path}`, {
    credentials: 'include',
    ...init
  })
  if (!res.ok) {
    const text = await res.text()
    let message = text || res.statusText
    let code: string | undefined
    try {
      const payload = JSON.parse(text)
      const detail = payload?.detail
      if (typeof detail === 'string') message = detail
      else if (detail && typeof detail === 'object') {
        message = detail.message || message
        code = detail.code
      }
    } catch {
      // Plain-text errors are already useful.
    }
    const error = new ApiError(message)
    error.status = res.status
    error.code = code
    throw error
  }
  if (!expectJson) return res
  return res.json()
}

export async function getSetupStatus(): Promise<SetupStatus> {
  return apiFetch('/api/setup/status')
}

export async function saveInitialSetup(payload: ProviderSettingsDraft): Promise<void> {
  await apiFetch('/api/setup', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export function makeDataUrl(path?: string | null): string {
  if (!path) return ''
  return `${BACKEND}${path}`
}

export async function register(payload: { username: string; password: string }): Promise<AuthUser> {
  return apiFetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function login(payload: {
  username: string
  password: string
  remember_me: boolean
}): Promise<AuthUser> {
  return apiFetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function getCurrentUser(): Promise<AuthUser> {
  return apiFetch('/api/auth/me')
}

export async function logout(): Promise<void> {
  await apiFetch('/api/auth/logout', { method: 'POST' })
}

export async function updateProfile(username: string): Promise<AuthUser> {
  return apiFetch('/api/auth/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username })
  })
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiFetch('/api/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword
    })
  })
}

export async function uploadAvatar(file: File): Promise<AuthUser> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch('/api/auth/avatar', {
    method: 'POST',
    body: form
  })
}

export async function updateSettings(payload: Partial<UserSettings>): Promise<UserSettings> {
  return apiFetch('/api/settings/me', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function updateProviderSettings(
  payload: Partial<ProviderSettingsDraft>
): Promise<UserSettings> {
  return apiFetch('/api/settings/me/providers', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export type UploadOptions = {
  visionCheckEnabled?: boolean
  visionCheckMode?: 'auto' | 'manual'
}

export async function uploadFile(file: File, options: UploadOptions = {}): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('vision_check_enabled', String(options.visionCheckEnabled ?? false))
  form.append('vision_check_mode', options.visionCheckMode ?? 'auto')
  return apiFetch('/api/upload', { method: 'POST', body: form })
}

export async function getDocumentStatus(documentId: string): Promise<DocumentStatus> {
  return apiFetch(`/api/document/${documentId}`)
}

export async function retryDocument(documentId: string): Promise<{
  document_id: string
  status: 'queued'
  resume_from: string
}> {
  return apiFetch(`/api/document/${documentId}/retry`, { method: 'POST' })
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  return apiFetch('/api/documents')
}

export async function deleteDocument(documentId: string): Promise<void> {
  await apiFetch(`/api/document/${documentId}`, { method: 'DELETE' })
}

export async function renameDocument(documentId: string, name: string): Promise<DocumentStatus> {
  return apiFetch(`/api/document/${documentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  })
}

export async function sendChat(payload: {
  document_id?: string
  document_ids?: string[]
  scope?: 'document' | 'library'
  session_id?: string
  message: string
  override_api_key?: string
  override_base_url?: string
  override_model?: string
}): Promise<{ answer: string; session_id: string }> {
  return apiFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function listChatSessions(
  scope: 'document' | 'library',
  documentId?: string
): Promise<ChatSession[]> {
  const params = new URLSearchParams({ scope })
  if (documentId) params.set('document_id', documentId)
  return apiFetch(`/api/chat/sessions?${params.toString()}`)
}

// Streaming chat (SSE).  Events: meta {session_id}, delta {text},
// done {answer, session_id}, error {message}.  Returns the final answer.
export async function streamChat(
  payload: Parameters<typeof sendChat>[0],
  handlers: { onMeta?: (sessionId: string) => void; onDelta?: (text: string) => void }
): Promise<{ answer: string; session_id: string; sources: SourceRefItem[] }> {
  const res = await fetch(`${BACKEND}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload)
  })
  if (!res.ok || !res.body) {
    const text = await res.text()
    let message = text || res.statusText
    try {
      const detail = JSON.parse(text)?.detail
      if (typeof detail === 'string') message = detail
    } catch {
      // Plain-text errors are already useful.
    }
    throw new ApiError(message)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer = ''
  let sessionId = ''
  let sources: SourceRefItem[] = []
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const chunk = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
      let eventName = 'message'
      const dataLines: string[] = []
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      let payloadData: any
      try {
        payloadData = JSON.parse(dataLines.join('\n'))
      } catch {
        continue
      }
      if (eventName === 'meta') {
        sessionId = payloadData.session_id || sessionId
        handlers.onMeta?.(sessionId)
      } else if (eventName === 'delta') {
        const text = payloadData.text || ''
        answer += text
        handlers.onDelta?.(text)
      } else if (eventName === 'done') {
        answer = payloadData.answer || answer
        sessionId = payloadData.session_id || sessionId
        sources = Array.isArray(payloadData.sources) ? payloadData.sources : sources
      } else if (eventName === 'error') {
        throw new ApiError(payloadData.message || '聊天请求失败')
      }
    }
  }
  return { answer, session_id: sessionId, sources }
}

export async function createChatSession(payload: {
  scope: 'document' | 'library'
  document_ids: string[]
  title?: string
}): Promise<ChatSession> {
  return apiFetch('/api/chat/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function getChatSession(sessionId: string): Promise<ChatSession> {
  return apiFetch(`/api/chat/sessions/${sessionId}`)
}

export async function locateCounterpart(payload: {
  documentId: string
  source_side: 'original' | 'translated'
  selected_text: string
  source_page?: number
  source_page_count?: number
}): Promise<{ target_text: string; position_ratio: number; confidence: number; alignment_method: string; highlight_text: string }> {
  return apiFetch(`/api/document/${payload.documentId}/locate-counterpart`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_side: payload.source_side,
      selected_text: payload.selected_text,
      source_page: payload.source_page,
      source_page_count: payload.source_page_count
    })
  })
}

export async function listAnnotations(documentId: string): Promise<AnnotationItem[]> {
  return apiFetch(`/api/document/${documentId}/annotations`)
}

export async function createAnnotation(
  documentId: string,
  payload: { page: number; quote: string; color: string; note: string; position_ratio: number }
): Promise<AnnotationItem> {
  return apiFetch(`/api/document/${documentId}/annotations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
}

export async function deleteAnnotation(documentId: string, annotationId: string): Promise<void> {
  await apiFetch(`/api/document/${documentId}/annotations/${annotationId}`, { method: 'DELETE' })
}

export async function updateReadingProgress(
  documentId: string,
  page: number,
  ratio: number
): Promise<void> {
  await apiFetch(`/api/document/${documentId}/progress`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page, ratio })
  })
}

export async function downloadNotes(documentId: string): Promise<void> {
  const res = await apiFetch(`/api/document/${documentId}/notes.md`, {}, false)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'reading-notes.md'
  link.click()
  URL.revokeObjectURL(url)
}

export async function getDocumentStructure(documentId: string): Promise<DocumentStructure> {
  return apiFetch(`/api/document/${documentId}/structure`)
}

export async function searchLibrary(query: string): Promise<LibrarySearchHit[]> {
  const params = new URLSearchParams({ q: query })
  return apiFetch(`/api/search?${params.toString()}`)
}

export async function getDocumentBibtex(documentId: string): Promise<{ bibtex: string; filename: string }> {
  return apiFetch(`/api/document/${documentId}/bibtex`)
}

export function translatedPdfName(sourceFilename: string): string {
  const leaf = (sourceFilename || 'document.pdf').split(/[\\/]/).pop() || 'document.pdf'
  const stem = leaf.replace(/\.[^.]+$/, '') || 'document'
  return `${stem}_Chinese_ver.pdf`
}

export async function createProject(name?: string): Promise<{ project_id: string; name: string }> {
  return apiFetch('/api/project', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(name ? { name } : {})
  })
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  return apiFetch(`/api/project/${projectId}`)
}

export async function uploadProjectFile(
  projectId: string,
  file: File,
  relativePath?: string
): Promise<ProjectDetail> {
  const form = new FormData()
  form.append('file', file)
  form.append('relative_path', relativePath || file.name)
  return apiFetch(`/api/project/${projectId}/files`, {
    method: 'POST',
    body: form
  })
}

export async function uploadProjectArchive(projectId: string, file: File): Promise<ProjectDetail> {
  const form = new FormData()
  form.append('file', file)
  return apiFetch(`/api/project/${projectId}/archive`, {
    method: 'POST',
    body: form
  })
}

export async function deleteProjectFiles(projectId: string, relativePaths: string[]): Promise<ProjectDetail> {
  return apiFetch(`/api/project/${projectId}/delete-files`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ relative_paths: relativePaths })
  })
}

export async function buildProject(
  projectId: string,
  mainTex: string,
  options: UploadOptions = {}
): Promise<UploadResult> {
  return apiFetch(`/api/project/${projectId}/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      main_tex: mainTex,
      vision_check_enabled: options.visionCheckEnabled ?? false,
      vision_check_mode: options.visionCheckMode ?? 'auto'
    })
  })
}

export async function postReviewDecision(
  documentId: string,
  accept: boolean,
  edits?: string
): Promise<void> {
  await apiFetch(`/api/document/${documentId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accept, edits })
  })
}

export async function getDocumentTex(documentId: string): Promise<DocumentTex> {
  const data = await apiFetch(`/api/document/${documentId}/tex`)
  return {
    tex_content: (data.tex_content as string) || '',
    path: (data.path as string) || ''
  }
}

export async function recompileDocument(
  documentId: string,
  texContent: string
): Promise<RecompileResult> {
  return apiFetch(`/api/document/${documentId}/tex`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tex_content: texContent })
  })
}

export async function revealDocumentTex(
  documentId: string,
  target: 'folder' | 'editor'
): Promise<{ ok: boolean; error?: string | null }> {
  return apiFetch(`/api/document/${documentId}/tex/reveal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target })
  })
}
