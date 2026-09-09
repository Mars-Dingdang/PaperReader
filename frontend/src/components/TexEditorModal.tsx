import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import {
  getDocumentTex,
  recompileDocument,
  revealDocumentTex,
  type LintIssue,
  type MissingChar
} from '../lib/api'
import type { TexEditorHandle } from './TexEditor'

const TexEditor = lazy(() => import('./TexEditor').then((m) => ({ default: m.TexEditor })))

type Props = {
  documentId: string
  onClose: () => void
  onCompiled?: (warning?: string | null) => void
}

export function TexEditorModal({ documentId, onClose, onCompiled }: Props) {
  const [original, setOriginal] = useState('')
  const [content, setContent] = useState('')
  const [path, setPath] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)
  const [issues, setIssues] = useState<LintIssue[]>([])
  const [missingChars, setMissingChars] = useState<MissingChar[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const editorRef = useRef<TexEditorHandle | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    setIssues([])
    setMissingChars([])
    getDocumentTex(documentId)
      .then((tex) => {
        if (!alive) return
        setOriginal(tex.tex_content)
        setContent(tex.tex_content)
        setPath(tex.path)
      })
      .catch((e) => {
        if (alive) setError(String(e))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [documentId])

  const copyPath = async () => {
    if (!path) return
    try {
      await navigator.clipboard.writeText(path)
      setNotice('路径已复制')
    } catch {
      setNotice(path)
    }
  }

  const reveal = async (target: 'folder' | 'editor') => {
    try {
      const res = await revealDocumentTex(documentId, target)
      setNotice(res.ok ? (target === 'editor' ? '已尝试用 VS Code 打开' : '已在文件管理器中显示') : res.error || '操作失败')
    } catch (e) {
      setNotice(String(e))
    }
  }

  const replaceCharEverywhere = (missing: MissingChar) => {
    if (!missing.suggest) return
    const count = editorRef.current?.replaceAllMatches(missing.char, `$${missing.suggest}$`) ?? 0
    setNotice(count > 0 ? `已替换 ${count} 处 ${missing.char} → $${missing.suggest}$（记得保存并重新编译）` : `未找到 ${missing.char}`)
  }

  const handleSave = async () => {
    setBusy(true)
    setError(null)
    setWarning(null)
    setIssues([])
    setMissingChars([])
    try {
      const res = await recompileDocument(documentId, content)
      if (!res.ok) {
        setError(res.error || '编译失败')
        setIssues(res.issues ?? [])
        setMissingChars(res.missing_chars ?? [])
        return
      }
      setWarning(res.warning ?? null)
      setIssues(res.issues ?? [])
      setMissingChars(res.missing_chars ?? [])
      onCompiled?.(res.warning ?? null)
      if (!res.warning) {
        onClose()
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 1080, width: '94vw' }}>
        <div className="modal-header">
          <div className="modal-title">编辑 translated.tex</div>
          <button className="icon-btn" onClick={onClose} title="关闭">×</button>
        </div>
        <div className="modal-body">
          {loading ? (
            <div className="muted">加载中…</div>
          ) : (
            <>
              <div className="tex-editor-toolbar">
                <button className="btn small" onClick={() => editorRef.current?.openSearch()} title="Ctrl+F / Ctrl+H">
                  查找 / 替换
                </button>
                <button className="btn small" onClick={copyPath} disabled={!path} title={path || ''}>
                  复制文件路径
                </button>
                <button className="btn small" onClick={() => reveal('folder')} disabled={!path}>
                  在文件管理器中显示
                </button>
                <button className="btn small" onClick={() => reveal('editor')} disabled={!path}>
                  用 VS Code 打开
                </button>
                <div className="editor-stats muted">
                  {content.length.toLocaleString()} 字符 · {content.split('\n').length.toLocaleString()} 行
                </div>
              </div>
              <Suspense fallback={<div className="muted" style={{ padding: 24 }}>加载编辑器…</div>}>
                <TexEditor
                  key={documentId}
                  ref={editorRef}
                  initialContent={content}
                  onChange={setContent}
                />
              </Suspense>
              {notice && <div className="tex-editor-notice">{notice}</div>}
              {issues.length > 0 && (
                <div className="error-panel" style={{ marginTop: 8 }}>
                  <div className="small">编译错误（点击跳转到对应行）：</div>
                  <div className="tex-issue-list">
                    {issues.slice(0, 12).map((issue, i) => (
                      <button
                        key={i}
                        className="tex-issue-item"
                        onClick={() => issue.line && editorRef.current?.goToLine(issue.line)}
                      >
                        {issue.line ? `第 ${issue.line} 行` : '—'}：{issue.message}
                      </button>
                    ))}
                    {issues.length > 12 && <div className="muted small">…共 {issues.length} 条</div>}
                  </div>
                </div>
              )}
              {missingChars.length > 0 && (
                <div className="warn-panel" style={{ marginTop: 8 }}>
                  <div className="small">字体缺少以下字符（渲染为空白），可一键替换：</div>
                  {missingChars.map((m) => (
                    <div key={m.codepoint} className="missing-char-row">
                      <span>
                        {m.char}（{m.codepoint}）× {m.count}
                        {m.suggest && <span className="muted"> → 建议 ${m.suggest}$</span>}
                      </span>
                      <span className="missing-char-actions">
                        <button className="btn small" onClick={() => editorRef.current?.openSearch(m.char, m.suggest ? `$${m.suggest}$` : undefined)}>
                          逐个查看
                        </button>
                        {m.suggest && (
                          <button className="btn small" onClick={() => replaceCharEverywhere(m)}>
                            全部替换
                          </button>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {error && issues.length === 0 && (
                <div className="error-panel" style={{ marginTop: 8 }}>
                  <div className="small">编译错误：</div>
                  <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 180, overflow: 'auto' }}>{error}</pre>
                </div>
              )}
              {warning && !error && (
                <div className="warn-panel" style={{ marginTop: 8 }}>
                  <div className="small">编译完成（含警告）：</div>
                  <pre style={{ whiteSpace: 'pre-wrap', maxHeight: 180, overflow: 'auto' }}>{warning}</pre>
                </div>
              )}
            </>
          )}
        </div>
        <div className="modal-footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={() => editorRef.current?.setContent(original)} disabled={busy || loading}>
            重置
          </button>
          <button className="btn" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="btn primary" onClick={handleSave} disabled={busy || loading}>
            {busy ? '编译中…' : '保存并重新编译'}
          </button>
        </div>
      </div>
    </div>
  )
}
