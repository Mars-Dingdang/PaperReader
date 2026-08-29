import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, BookOpenCheck, CheckCheck, LibraryBig } from 'lucide-react'
import type { DocumentSummary } from '../lib/api'
import { ChatPanel } from './ChatPanel'


type Props = {
  documents: DocumentSummary[]
  onClose: () => void
}


export function LiteratureChatPage({ documents, onClose }: Props) {
  const available = useMemo(
    () => documents.filter((item) => item.status === 'done'),
    [documents]
  )
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  useEffect(() => {
    setSelectedIds((previous) => {
      const valid = previous.filter((id) => available.some((item) => item.document_id === id))
      return valid.length > 0 ? valid : available.map((item) => item.document_id)
    })
  }, [available])

  const allSelected = available.length > 0 && selectedIds.length === available.length

  return (
    <section className="literature-page">
      <header className="literature-page-header">
        <button className="icon-btn" title="返回论文阅读" onClick={onClose}>
          <ArrowLeft size={18} />
        </button>
        <div className="literature-page-title">
          <LibraryBig size={22} />
          <div>
            <h2>AI Literature Chat</h2>
            <p>优先检索你上传的论文，并用联网学术资料补充回答</p>
          </div>
        </div>
      </header>

      <div className="literature-page-body">
        <aside className="literature-sources">
          <div className="literature-sources-head">
            <span><BookOpenCheck size={16} /> 论文资料库</span>
            <button
              className="small-link-btn"
              disabled={available.length === 0}
              onClick={() => setSelectedIds(allSelected ? [] : available.map((item) => item.document_id))}
            >
              <CheckCheck size={13} /> {allSelected ? '取消全选' : '选择全部'}
            </button>
          </div>
          <p className="muted small">勾选一篇进行讨论，或勾选多篇进行联动比较。</p>
          <div className="literature-source-list">
            {available.length === 0 ? (
              <div className="muted small">暂无已完成的论文，请先上传并完成翻译。</div>
            ) : available.map((doc) => (
              <label key={doc.document_id} className="literature-source-item">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(doc.document_id)}
                  onChange={(event) => {
                    setSelectedIds((ids) => event.target.checked
                      ? [...ids, doc.document_id]
                      : ids.filter((id) => id !== doc.document_id)
                    )
                  }}
                />
                <span title={doc.source_filename}>{doc.source_filename || doc.document_id}</span>
              </label>
            ))}
          </div>
          <div className="literature-source-count">
            已选择 {selectedIds.length} / {available.length} 篇
          </div>
        </aside>

        <ChatPanel
          className="literature-chat"
          scope="library"
          documentIds={selectedIds}
          references={[]}
          title="跨论文研究助手"
          greeting="Hi，有什么可以帮你的？你可以让我总结、批判或比较所选论文。"
        />
      </div>
    </section>
  )
}
