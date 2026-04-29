import { useState } from 'react'
import { X } from 'lucide-react'
import { postReviewDecision, type ReviewProposalItem } from '../lib/api'

type Props = {
  documentId: string
  proposals: ReviewProposalItem[]
  onResolved: () => void
}

export function ReviewModal({ documentId, proposals, onResolved }: Props) {
  const [busy, setBusy] = useState(false)
  const [activeIdx, setActiveIdx] = useState(0)
  const active = proposals[activeIdx]
  const [edited, setEdited] = useState<string>('')
  const [editing, setEditing] = useState(false)

  if (!active) return null

  async function decide(accept: boolean, edits?: string) {
    setBusy(true)
    try {
      await postReviewDecision(documentId, accept, edits)
      onResolved()
    } catch (e: any) {
      alert(`提交失败：${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay">
      <div className="modal-card" style={{ width: 'min(960px, 95vw)' }}>
        <div className="modal-header">
          <div className="modal-title">视觉模型校验 · 待审核 ({proposals.length})</div>
          <button className="icon-btn" title="忽略并保留原文" onClick={() => void decide(false)}>
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          {proposals.length > 1 && (
            <div className="small" style={{ marginBottom: 8 }}>
              {proposals.map((p, i) => (
                <button
                  key={i}
                  className={`btn ${i === activeIdx ? 'primary' : ''}`}
                  style={{ marginRight: 6, padding: '4px 10px' }}
                  onClick={() => setActiveIdx(i)}
                >
                  Page {p.page_index + 1}
                </button>
              ))}
            </div>
          )}
          {active.issues?.length > 0 && (
            <ul className="review-issues">
              {active.issues.map((i, k) => <li key={k}>{i}</li>)}
            </ul>
          )}
          <div className="review-grid">
            <div>
              <div className="small muted" style={{ marginBottom: 4 }}>原文</div>
              <pre className="review-pre">{active.original_md}</pre>
            </div>
            <div>
              <div className="small muted" style={{ marginBottom: 4 }}>建议</div>
              {editing ? (
                <textarea
                  className="review-pre"
                  style={{ width: '100%', height: 360 }}
                  value={edited}
                  onChange={(e) => setEdited(e.target.value)}
                />
              ) : (
                <pre className="review-pre">{active.proposed_md}</pre>
              )}
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn" disabled={busy} onClick={() => void decide(false)}>拒绝</button>
          {!editing && (
            <button className="btn" disabled={busy} onClick={() => { setEdited(active.proposed_md); setEditing(true) }}>编辑后采纳</button>
          )}
          {editing && (
            <button className="btn" disabled={busy} onClick={() => setEditing(false)}>取消编辑</button>
          )}
          <button
            className="btn primary"
            disabled={busy}
            onClick={() => void decide(true, editing ? edited : undefined)}
          >
            {busy ? '提交中…' : '采纳'}
          </button>
        </div>
      </div>
    </div>
  )
}
