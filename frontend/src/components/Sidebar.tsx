import { useEffect, useRef, useState } from 'react'
import {
  ChevronRight,
  Eye,
  FileText,
  FolderOpen,
  MessageSquareText,
  Moon,
  PanelLeftClose,
  Pencil,
  Plus,
  RefreshCw,
  Star,
  Sun,
} from 'lucide-react'
import type { ArtifactItem, DocumentSummary } from '../lib/api'
import { makeDataUrl } from '../lib/api'
import { ArtifactPreviewTip } from './ArtifactPreviewTip'

type Tab = 'tasks' | 'favorites'

type Props = {
  documents: DocumentSummary[]
  activeDocumentId?: string
  favorites: string[]
  uploading: boolean
  artifacts: ArtifactItem[]
  logs: string[]
  theme: 'light' | 'dark'
  chatVisible: boolean
  visionEnabled: boolean
  visionMode: 'auto' | 'manual'
  activeStatus?: string
  onUpload: (file: File) => void
  onSelect: (documentId: string) => void
  onToggleFavorite: (documentId: string) => void
  onCollapse: () => void
  onOpenInPane?: (artifact: ArtifactItem) => void
  onEditTex?: (artifact: ArtifactItem) => void
  onNewProject?: () => void
  onToggleChat: () => void
  onToggleVision: () => void
  onToggleTheme: () => void
  onRefreshStatus: () => void
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
  theme,
  chatVisible,
  visionEnabled,
  visionMode,
  activeStatus,
  onUpload,
  onSelect,
  onToggleFavorite,
  onCollapse,
  onOpenInPane,
  onEditTex,
  onNewProject,
  onToggleChat,
  onToggleVision,
  onToggleTheme,
  onRefreshStatus,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [tab, setTab] = useState<Tab>('tasks')
  const [showArtifacts, setShowArtifacts] = useState(true)
  const [showLogs, setShowLogs] = useState(false)
  const [hoverPreview, setHoverPreview] = useState<{ artifact: ArtifactItem; rect: DOMRect } | null>(null)
  const hoverTimerRef = useRef<number | null>(null)
  useEffect(() => () => {
    if (hoverTimerRef.current) window.clearTimeout(hoverTimerRef.current)
  }, [])

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
        <button className="icon-btn" title="收起侧栏" onClick={onCollapse}>
          <PanelLeftClose size={18} />
        </button>
      </div>

      <div className="sidebar-toolbar" role="toolbar" aria-label="工具">
        <button
          className={`icon-btn ${chatVisible ? 'active' : ''}`}
          title={chatVisible ? '关闭对话' : '打开对话'}
          onClick={onToggleChat}
        >
          <MessageSquareText size={16} />
        </button>
        <button
          className={`icon-btn vision-btn ${visionEnabled ? 'active' : ''}`}
          title={`视觉校验：${visionEnabled ? `开 (${visionMode === 'manual' ? '人工' : '自动'})` : '关'} · 点击切换`}
          onClick={onToggleVision}
        >
          <span className="vision-glyph">
            {visionEnabled ? (visionMode === 'manual' ? '人' : '自') : '×'}
          </span>
        </button>
        <button
          className="icon-btn"
          title={`刷新状态：${activeStatus ?? '—'}`}
          onClick={onRefreshStatus}
        >
          <RefreshCw size={16} />
        </button>
        <div className="toolbar-spacer" />
        <button
          className="icon-btn"
          title={theme === 'dark' ? '切换到浅色' : '切换到深色'}
          onClick={onToggleTheme}
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
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
      {onNewProject && (
        <button
          className="new-parse-btn secondary"
          onClick={onNewProject}
        >
          <FolderOpen size={16} />
          TeX 项目
        </button>
      )}
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
                    const isPdf = item.kind.includes('pdf') || /\.pdf$/i.test(item.name)
                    const onMouseEnter = (e: React.MouseEvent<HTMLDivElement>) => {
                      if (!item.url) return
                      const rect = e.currentTarget.getBoundingClientRect()
                      if (hoverTimerRef.current) window.clearTimeout(hoverTimerRef.current)
                      hoverTimerRef.current = window.setTimeout(() => {
                        setHoverPreview({ artifact: item, rect })
                      }, 220)
                    }
                    const onMouseLeave = () => {
                      if (hoverTimerRef.current) window.clearTimeout(hoverTimerRef.current)
                      hoverTimerRef.current = null
                      setHoverPreview(null)
                    }
                    return (
                      <div
                        key={`${item.path}-${idx}`}
                        className="artifact-item"
                        draggable={!!item.url}
                        onDragStart={(e) => {
                          if (!item.url) return
                          const payload = JSON.stringify({ url: makeDataUrl(item.url), name: item.name, kind: item.kind })
                          e.dataTransfer.setData('application/x-paperreader-artifact', payload)
                          e.dataTransfer.setData('text/plain', payload)
                          e.dataTransfer.effectAllowed = 'copy'
                        }}
                        onMouseEnter={onMouseEnter}
                        onMouseLeave={onMouseLeave}
                        title={item.url ? '拖拽到 PDF 区域可预览，悬浮可见缩略图' : ''}
                      >
                        <div className="artifact-name">{item.name}</div>
                        <div className="artifact-meta">
                          <span className="muted small">{item.kind}</span>
                          <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            {isPdf && onOpenInPane && (
                              <button
                                className="icon-btn artifact-open"
                                title="在阅读器中打开"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  onOpenInPane(item)
                                }}
                              >
                                <Eye size={12} />
                              </button>
                            )}
                            {item.name === 'translated.tex' && onEditTex && (
                              <button
                                className="icon-btn artifact-open"
                                title="编辑并重新编译"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  onEditTex(item)
                                }}
                              >
                                <Pencil size={12} />
                              </button>
                            )}
                            {href && (
                              <a href={href} target="_blank" rel="noreferrer" className="small">打开</a>
                            )}
                          </span>
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
      {hoverPreview && hoverPreview.artifact.url && (
        <ArtifactPreviewTip
          url={hoverPreview.artifact.url}
          kind={hoverPreview.artifact.kind}
          name={hoverPreview.artifact.name}
          anchorRect={hoverPreview.rect}
        />
      )}
    </aside>
  )
}
