import { useEffect, useState } from 'react'
import { getDocumentTex, recompileDocument } from '../lib/api'

type Props = {
  documentId: string
  onClose: () => void
  onCompiled?: (warning?: string | null) => void
}

export function TexEditorModal({ documentId, onClose, onCompiled }: Props) {
  const [original, setOriginal] = useState('')
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [warning, setWarning] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    getDocumentTex(documentId)
      .then((tex) => {
        if (!alive) return
        setOriginal(tex)
        setContent(tex)
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

  const handleSave = async () => {
    setBusy(true)
    setError(null)
    setWarning(null)
    try {
      const res = await recompileDocument(documentId, content)
      if (!res.ok) {
        setError(res.error || '编译失败')
        return
      }
      setWarning(res.warning ?? null)
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
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 980, width: '92vw' }}>
        <div className="modal-header">
          <div className="modal-title">编辑 translated.tex</div>
          <button className="icon-btn" onClick={onClose} title="关闭">×</button>
        </div>
        <div className="modal-body">
          {loading ? (
            <div className="muted">加载中…</div>
          ) : (
            <>
              <textarea
                className="tex-editor-textarea"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                spellCheck={false}
              />
              {error && (
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
          <button className="btn" onClick={() => setContent(original)} disabled={busy || loading}>
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
