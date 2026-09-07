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
}

export type UserSettings = {
  api_key: string
  base_url: string
  model: string
  theme: 'light' | 'dark'
  vision_enabled: boolean
  vision_mode: 'auto' | 'manual'
  favorites: string[]
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

export type RecompileResult = {
  ok: boolean
  pdf_url?: string | null
  warning?: string | null
  error?: string | null
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

async function apiFetch(path: string, init: RequestInit = {}, expectJson = true) {
  const res = await fetch(`${BACKEND}${path}`, {
    credentials: 'include',
    ...init
  })
  if (!res.ok) {
    const text = await res.text()
    const message = text || res.statusText
    const error = new Error(message) as Error & { status?: number }
    error.status = res.status
    throw error
  }
  if (!expectJson) return res
  return res.json()
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
}): Promise<{ target_text: string; position_ratio: number; confidence: number; alignment_method: string }> {
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

export async function getDocumentTex(documentId: string): Promise<string> {
  const data = await apiFetch(`/api/document/${documentId}/tex`)
  return (data.tex_content as string) || ''
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
