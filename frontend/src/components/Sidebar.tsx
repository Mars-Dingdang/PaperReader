import { useEffect, useRef, useState } from 'react'
import {
  ChevronRight,
  Eye,
  FileText,
  FolderOpen,
  LogOut,
  MessageSquareText,
  Moon,
  PanelLeftClose,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Star,
  Sun,
  Trash2,
} from 'lucide-react'
import type { ArtifactItem, AuthUser, DocumentSummary, LibrarySearchHit } from '../lib/api'
import { getDocumentBibtex, makeDataUrl, searchLibrary } from '../lib/api'
import { ArtifactPreviewTip } from './ArtifactPreviewTip'

type Tab = 'tasks' | 'favorites'

type Props = {
  user: AuthUser
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
  onDelete: (documentId: string) => void
  onRename: (documentId: string, name: string) => void
  onCollapse: () => void
  onOpenInPane?: (artifact: ArtifactItem) => void
  onEditTex?: (artifact: ArtifactItem) => void
  onNewProject?: () => void
  onOpenProfile: () => void
  onLogout: () => void
  onToggleChat: () => void
  onToggleVision: () => void
  onToggleTheme: () => void
  onRefreshStatus: () => void
  onOpenLiteratureChat: () => void
  literatureChatOpen: boolean
  onSearchLocate: (hit: LibrarySearchHit) => void
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

function formatTime(value?: string | null): string {
  if (!value) return '刚刚创建'
  return new Date(value).toLocaleString()
}

export function Sidebar({
  user,
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
  onDelete,
  onRename,
  onCollapse,
  onOpenInPane,
  onEditTex,
  onNewProject,
  onOpenProfile,
  onLogout,
  onToggleChat,
  onToggleVision,
  onToggleTheme,
  onRefreshStatus,
  onOpenLiteratureChat,
  literatureChatOpen,
  onSearchLocate,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [tab, setTab] = useState<Tab>('tasks')
  const [showArtifacts, setShowArtifacts] = useState(true)
  const [showLogs, setShowLogs] = useState(false)
  const [hoverPreview, setHoverPreview] = useState<{ artifact: ArtifactItem; rect: DOMRect } | null>(null)
  const [contextMenu, setContextMenu] = useState<{ documentId: string; x: number; y: number } | null>(null)
  const hoverTimerRef = useRef<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchHits, setSearchHits] = useState<LibrarySearchHit[]>([])
  const [searching, setSearching] = useState(false)

  // Full-text library search with a light debounce; empty query clears.
  useEffect(() => {
    const query = searchQuery.trim()
    if (!query) {
      setSearchHits([])
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = window.setTimeout(() => {
      void searchLibrary(query)
        .then((hits) => setSearchHits(hits))
        .catch(() => setSearchHits([]))
        .finally(() => setSearching(false))
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchQuery])

  async function exportBibtex(documentId: string) {
    try {
      const { bibtex, filename } = await getDocumentBibtex(documentId)
      const blob = new Blob([bibtex], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      alert(`导出 BibTeX 失败：${e?.message ?? String(e)}`)
    }
  }

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

      <button
        className={`literature-chat-entry ${literatureChatOpen ? 'active' : ''}`}
        onClick={onOpenLiteratureChat}
      >
        <span className="literature-chat-icon"><Sparkles size={17} /></span>
        <span>
          <strong>AI Literature Chat</strong>
          <small>跨论文检索、比较与讨论</small>
        </span>
        <ChevronRight size={14} />
      </button>

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
        accept=".pdf,.tex,.zip,.tar,.tar.gz,.tgz"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (!file) return
          onUpload(file)
          e.currentTarget.value = ''
        }}
      />
      <div className="sidebar-latex-recommendation">
        有 LaTeX 源码时请优先上传，结构与翻译质量更好。
      </div>

      <nav className="sidebar-nav">
        <button
          className={`nav-item ${tab === 'tasks' ? 'active' : ''}`}
          onClick={() => setTab('tasks')}
        >
          <FolderOpen size={16} />
          历史记录
        </button>
        <button
          className={`nav-item ${tab === 'favorites' ? 'active' : ''}`}
          onClick={() => setTab('favorites')}
        >
          <Star size={16} />
          我的收藏
        </button>
      </nav>

      <div className="library-search">
        <Search size={14} />
        <input
          type="text"
          placeholder="全文搜索文献库…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery && (
          <button className="icon-btn" title="清除搜索" onClick={() => setSearchQuery('')}>
            <Trash2 size={12} />
          </button>
        )}
      </div>

      <div className="sidebar-scroll">
        <div className="sidebar-divider" />

        {searchQuery.trim() ? (
          <div className="doc-list">
            {searching ? (
              <div className="muted small" style={{ padding: 12 }}>搜索中…</div>
            ) : searchHits.length === 0 ? (
              <div className="muted small" style={{ padding: 12 }}>没有匹配的文本</div>
            ) : (
              searchHits.map((hit) => (
                <button
                  key={`${hit.document_id}-${hit.side}`}
                  className={`doc-item search-hit ${hit.document_id === activeDocumentId ? 'active' : ''}`}
                  onClick={() => onSearchLocate(hit)}
                  title={hit.snippet}
                >
                  <div className="doc-icon"><FileText size={18} /></div>
                  <div className="doc-meta">
                    <div className="doc-name">{hit.document_title}</div>
                    <div className="doc-sub">
                      <span className="muted small">{hit.side === 'original' ? '原文' : '译文'}</span>
                    </div>
                    <div className="muted tiny">{hit.snippet.slice(0, 60)}…</div>
                  </div>
                </button>
              ))
            )}
          </div>
        ) : (
        <div className="doc-list">
        {visible.length === 0 ? (
          <div className="muted small" style={{ padding: '12px' }}>
            {tab === 'favorites' ? '尚无收藏' : '暂无历史记录，点击「新解析」上传文件'}
          </div>
        ) : (
          visible.map((doc) => {
            const active = doc.document_id === activeDocumentId
            const fav = favorites.includes(doc.document_id)
            const displayName = doc.title || doc.source_filename || doc.document_id
            return (
              <div
                key={doc.document_id}
                className={`doc-item ${active ? 'active' : ''}`}
                onClick={() => onSelect(doc.document_id)}
                onContextMenu={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  setContextMenu({ documentId: doc.document_id, x: e.clientX, y: e.clientY })
                }}
              >
                <div className="doc-icon">
                  <FileText size={20} />
                </div>
                <div className="doc-meta">
                  <div className="doc-name" title={doc.source_filename}>{displayName}</div>
                  <div className="doc-sub">
                    <span>{doc.year || formatSize(doc.size_bytes)}</span>
                    <StatusBadge status={doc.status} />
                  </div>
                  <div className="muted tiny">{formatTime(doc.last_opened_at || doc.updated_at || doc.created_at)}</div>
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
                <button
                  className="star-btn"
                  title="移除历史"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(doc.document_id)
                  }}
                >
                  <Trash2 size={14} />
                </button>
                <ChevronRight size={14} className="chev" />
              </div>
            )
          })
        )}
      </div>
        )}

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
      </div>

      <div className="sidebar-divider" />
      <div className="account-card">
        <div className="account-main">
          {user.avatar_url ? (
            <img src={makeDataUrl(user.avatar_url)} alt={user.username} className="avatar-image" />
          ) : (
            <div className="avatar-fallback">{user.username.slice(0, 1).toUpperCase()}</div>
          )}
          <div className="account-meta">
            <div className="account-name">{user.username}</div>
            <div className="muted small">最近登录：{formatTime(user.last_login_at)}</div>
          </div>
        </div>
        <div className="account-actions">
          <button className="btn small-btn" onClick={onOpenProfile}>
            <Settings size={14} />
            个人中心
          </button>
          <button className="btn small-btn" onClick={onLogout}>
            <LogOut size={14} />
            退出
          </button>
        </div>
      </div>

      {hoverPreview && hoverPreview.artifact.url && (
        <ArtifactPreviewTip
          url={hoverPreview.artifact.url}
          kind={hoverPreview.artifact.kind}
          name={hoverPreview.artifact.name}
          anchorRect={hoverPreview.rect}
        />
      )}

      {contextMenu && (
        <>
          <div
            className="context-menu-overlay"
            onClick={() => setContextMenu(null)}
            onContextMenu={(e) => {
              e.preventDefault()
              setContextMenu(null)
            }}
          />
          <div className="context-menu" style={{ top: contextMenu.y, left: contextMenu.x }}>
            <button
              className="context-menu-item"
              onClick={() => {
                const id = contextMenu.documentId
                const current = documents.find((item) => item.document_id === id)?.source_filename || ''
                setContextMenu(null)
                const next = window.prompt('请输入新的文档名', current)
                if (next && next.trim() && next.trim() !== current) {
                  onRename(id, next.trim())
                }
              }}
            >
              <Pencil size={14} />
              更改文档名
            </button>
            <button
              className="context-menu-item"
              onClick={() => {
                const id = contextMenu.documentId
                setContextMenu(null)
                void exportBibtex(id)
              }}
            >
              <FileText size={14} />
              导出 BibTeX
            </button>
            <button
              className="context-menu-item danger"
              onClick={() => {
                const id = contextMenu.documentId
                setContextMenu(null)
                onDelete(id)
              }}
            >
              <Trash2 size={14} />
              删除文档
            </button>
          </div>
        </>
      )}
    </aside>
  )
}
