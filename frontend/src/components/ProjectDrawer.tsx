import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import {
  buildProject,
  createProject,
  deleteProjectFiles,
  getProject,
  uploadProjectArchive,
  uploadProjectFile,
  type ProjectDetail
} from '../lib/api'

type Props = {
  open: boolean
  onClose: () => void
  onBuilt: (documentId: string) => void
  visionCheckEnabled: boolean
  visionCheckMode: 'auto' | 'manual'
  initialArchive?: File | null
  onArchiveConsumed?: () => void
}

function isArchive(filename: string): boolean {
  return /\.(?:zip|tar|tar\.gz|tgz)$/i.test(filename)
}

export function ProjectDrawer({
  open,
  onClose,
  onBuilt,
  visionCheckEnabled,
  visionCheckMode,
  initialArchive,
  onArchiveConsumed,
}: Props) {
  const [project, setProject] = useState<ProjectDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [mainTex, setMainTex] = useState<string>('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const importedArchiveRef = useRef<File | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    if (project) return
    void (async () => {
      try {
        const created = await createProject()
        const detail = await getProject(created.project_id)
        setProject(detail)
      } catch (e: any) {
        setError(e?.message || String(e))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (project?.main_tex) setMainTex(project.main_tex)
    else if (project?.main_candidates?.[0]) setMainTex(project.main_candidates[0])
  }, [project])

  useEffect(() => {
    if (!open || !project || !initialArchive || importedArchiveRef.current === initialArchive) return
    importedArchiveRef.current = initialArchive
    setBusy(true)
    setError(null)
    void uploadProjectArchive(project.project_id, initialArchive)
      .then((detail) => {
        setProject(detail)
        onArchiveConsumed?.()
      })
      .catch((e: any) => setError(e?.message || String(e)))
      .finally(() => setBusy(false))
  }, [initialArchive, onArchiveConsumed, open, project])

  function handleClose() {
    if (busy) return
    importedArchiveRef.current = null
    onArchiveConsumed?.()
    onClose()
  }

  async function handleFiles(files: FileList | File[]) {
    if (!project) return
    setBusy(true)
    setError(null)
    try {
      let detail = project
      for (const f of Array.from(files)) {
        if (isArchive(f.name)) {
          detail = await uploadProjectArchive(project.project_id, f)
        } else {
          // Use webkitRelativePath when available (folder upload), else file name.
          const rel = (f as any).webkitRelativePath || f.name
          detail = await uploadProjectFile(project.project_id, f, rel)
        }
      }
      setProject(detail)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  async function removeFile(rel: string) {
    if (!project) return
    setBusy(true)
    try {
      const detail = await deleteProjectFiles(project.project_id, [rel])
      setProject(detail)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleBuild() {
    if (!project || !mainTex) return
    setBusy(true)
    setError(null)
    try {
      const result = await buildProject(project.project_id, mainTex, {
        visionCheckEnabled,
        visionCheckMode
      })
      onBuilt(result.document_id)
      importedArchiveRef.current = null
      onClose()
      setProject(null)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">新建 TeX 项目</div>
          <button className="icon-btn" title="关闭" onClick={handleClose} disabled={busy}>
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          {error && <div className="small" style={{ color: 'var(--danger)', marginBottom: 8 }}>{error}</div>}
          <div
            className={`dropzone ${dragOver ? 'over' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragOver(false)
              if (e.dataTransfer.files?.length) void handleFiles(e.dataTransfer.files)
            }}
            onClick={() => fileInputRef.current?.click()}
            role="button"
          >
            拖拽 LaTeX 文件或 .zip / .tar / .tar.gz / .tgz 工程包到此
            <div className="small" style={{ marginTop: 4 }}>压缩包会在本地安全解压 · 单文件最大 20MB</div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".tex,.bib,.cls,.sty,.bst,.bbl,.png,.jpg,.jpeg,.pdf,.eps,.svg,.gif,.csv,.tsv,.txt,.md,.zip,.tar,.tar.gz,.tgz"
            style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files?.length) void handleFiles(e.target.files)
              e.currentTarget.value = ''
            }}
          />
          <div className="latex-recommendation">
            arXiv 或论文提供 LaTeX 源码时，优先上传 LaTeX，可获得更好的结构与翻译质量。
          </div>
          <div className="small muted" style={{ marginBottom: 4 }}>
            已上传文件 ({project?.files.length ?? 0})
          </div>
          <div style={{ maxHeight: 240, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
            {project?.files.length === 0 && (
              <div className="muted small" style={{ padding: 12 }}>暂无文件</div>
            )}
            {project?.files.map((f) => (
              <div key={f.relative_path} className="project-file-row">
                <input
                  type="radio"
                  name="main_tex"
                  disabled={f.kind !== 'tex'}
                  checked={mainTex === f.relative_path}
                  onChange={() => setMainTex(f.relative_path)}
                  title={f.kind === 'tex' ? '设为主文件' : '仅 .tex 可作为主文件'}
                />
                <span className="file-rel" title={f.relative_path}>{f.relative_path}</span>
                <span className="muted small">{f.kind} · {(f.size / 1024).toFixed(1)} KB</span>
                <button className="icon-btn" title="删除" onClick={() => void removeFile(f.relative_path)}>
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={handleClose} disabled={busy}>取消</button>
          <button
            className="btn primary"
            disabled={busy || !mainTex}
            onClick={() => void handleBuild()}
          >
            {busy ? '处理中…' : `开始解析（main: ${mainTex || '—'}）`}
          </button>
        </div>
      </div>
    </div>
  )
}
