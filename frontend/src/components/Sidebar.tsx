import { useRef, useState } from 'react'
import {
  ChevronRight,
  FileText,
  FolderOpen,
  PanelLeftClose,
  Plus,
  Star
} from 'lucide-react'
import type { ArtifactItem, DocumentSummary } from '../lib/api'
import { makeDataUrl } from '../lib/api'

type Tab = 'tasks' | 'favorites'

type Props = {
  documents: DocumentSummary[]
  activeDocumentId?: string
  favorites: string[]
  uploading: boolean
  artifacts: ArtifactItem[]
  logs: string[]
  onUpload: (file: File) => void
  onSelect: (documentId: string) => void
  onToggleFavorite: (documentId: string) => void
  onCollapse: () => void
}

function formatSize(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === 'done' ? 'badge done' : status === 'failed' ? 'badge failed' : 'badge pending'
  return <span className={cls}>{status}</span>
}

export function Sidebar({
  documents,
  activeDocumentId,
  favorites,
  uploading,
  artifacts,
  logs,
  onUpload,
  onSelect,
  onToggleFavorite,
  onCollapse
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [tab, setTab] = useState<Tab>('tasks')
  const [showArtifacts, setShowArtifacts] = useState(true)
  const [showLogs, setShowLogs] = useState(false)

  const visible =
    tab === 'favorites'
      ? documents.filter((d) => favorites.includes(d.document_id))
      : documents

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="brand">
          <span className="brand-dot" />
          PaperReader
        </div>
        <button className="icon-btn" title="Collapse" onClick={onCollapse}>
          <PanelLeftClose size={18} />
        </button>
      </div>

      <button
        className="new-parse-btn"
        disabled={uploading}
        onClick={() => fileInputRef.current?.click()}
      >
        <Plus size={16} />
        {uploading ? '上传中…' : '新解析'}
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.tex"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (!file) return
          onUpload(file)
          e.currentTarget.value = ''
        }}
      />

      <nav className="sidebar-nav">
        <button
          className={`nav-item ${tab === 'tasks' ? 'active' : ''}`}
          onClick={() => setTab('tasks')}
        >
          <FolderOpen size={16} />
          任务管理
        </button>
        <button
          className={`nav-item ${tab === 'favorites' ? 'active' : ''}`}
          onClick={() => setTab('favorites')}
        >
          <Star size={16} />
          我的收藏
        </button>
      </nav>

      <div className="sidebar-divider" />

      <div className="doc-list">
        {visible.length === 0 ? (
          <div className="muted small" style={{ padding: '12px' }}>
            {tab === 'favorites' ? '尚无收藏' : '暂无任务，点击「新解析」上传文件'}
          </div>
        ) : (
          visible.map((doc) => {
            const active = doc.document_id === activeDocumentId
            const fav = favorites.includes(doc.document_id)
            return (
              <div
                key={doc.document_id}
                className={`doc-item ${active ? 'active' : ''}`}
                onClick={() => onSelect(doc.document_id)}
              >
                <div className="doc-icon">
                  <FileText size={20} />
                </div>
                <div className="doc-meta">
                  <div className="doc-name">{doc.source_filename || doc.document_id}</div>
                  <div className="doc-sub">
                    <span>{formatSize(doc.size_bytes)}</span>
                    <StatusBadge status={doc.status} />
                  </div>
                </div>
                <button
                  className={`star-btn ${fav ? 'on' : ''}`}
                  title={fav ? '取消收藏' : '收藏'}
                  onClick={(e) => {
                    e.stopPropagation()
                    onToggleFavorite(doc.document_id)
                  }}
                >
                  <Star size={14} fill={fav ? 'currentColor' : 'none'} />
                </button>
                <ChevronRight size={14} className="chev" />
              </div>
            )
          })
        )}
      </div>

      {activeDocumentId && (
        <>
          <div className="sidebar-divider" />
          <div className="sidebar-section">
            <button className="section-toggle" onClick={() => setShowArtifacts((v) => !v)}>
              <ChevronRight size={12} className={`chev-toggle ${showArtifacts ? 'open' : ''}`} />
              产物文件 ({artifacts.length})
            </button>
            {showArtifacts && (
              <div className="artifact-list">
                {artifacts.length === 0 ? (
                  <div className="muted small" style={{ padding: '4px 12px' }}>暂无</div>
                ) : (
                  artifacts.map((item, idx) => {
                    const href = item.url ? makeDataUrl(item.url) : ''
                    return (
                      <div key={`${item.path}-${idx}`} className="artifact-item">
                        <div className="artifact-name" title={item.name}>{item.name}</div>
                        <div className="artifact-meta">
                          <span className="muted small">{item.kind}</span>
                          {href && (
                            <a href={href} target="_blank" rel="noreferrer" className="small">打开</a>
                          )}
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            )}
          </div>

          <div className="sidebar-section">
            <button className="section-toggle" onClick={() => setShowLogs((v) => !v)}>
              <ChevronRight size={12} className={`chev-toggle ${showLogs ? 'open' : ''}`} />
              日志 ({logs.length})
            </button>
            {showLogs && (
              <div className="log-list">
                {logs.length === 0 ? (
                  <div className="muted small" style={{ padding: '4px 12px' }}>暂无</div>
                ) : (
                  logs.map((l, i) => (
                    <div key={i} className="log-line">{l}</div>
                  ))
                )}
              </div>
            )}
          </div>
        </>
      )}
    </aside>
  )
}
