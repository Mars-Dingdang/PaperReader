import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { AlertCircle, PanelLeftOpen, PanelRightOpen, UploadCloud } from 'lucide-react'
import { ChatPanel } from '../components/ChatPanel'
import { LiteratureChatPage } from '../components/LiteratureChatPage'
import { PdfPane } from '../components/PdfPane'
import type { AnnotationItem, PdfPaneHandle } from '../components/PdfPane'
import type { FigureItem } from '../lib/api'
import type { OutlineItem } from '../lib/pdfOutline'
import { ProgressBar } from '../components/ProgressBar'
import { ProfileModal } from '../components/ProfileModal'
import { ProjectDrawer } from '../components/ProjectDrawer'
import { ReviewModal } from '../components/ReviewModal'
import { Sidebar } from '../components/Sidebar'
import { TexEditorModal } from '../components/TexEditorModal'
import type { ArtifactItem, AuthUser, DocumentStatus, DocumentSummary, SourceRefItem, UserSettings } from '../lib/api'
import {
  createAnnotation,
  deleteAnnotation,
  deleteDocument,
  downloadNotes,
  getDocumentStatus,
  getDocumentStructure,
  listAnnotations,
  listDocuments,
  logout,
  locateCounterpart,
  makeDataUrl,
  renameDocument,
  retryDocument,
  translatedPdfName,
  updateReadingProgress,
  updateSettings,
  uploadFile
} from '../lib/api'

type OverridePdf = { url: string; name: string } | null
type PaneSide = 'original' | 'translated'
type PendingLocate = { text: string; side: 'original' | 'translated' } | null
type PendingQuote = { text: string; nonce: number } | null

type Props = {
  user: AuthUser
  onUserChange: (user: AuthUser) => void
  onLogout: () => void
}

export function ReaderPage({ user, onUserChange, onLogout }: Props) {
  const [summaries, setSummaries] = useState<DocumentSummary[]>([])
  const [activeId, setActiveId] = useState<string | undefined>(undefined)
  const [docCache, setDocCache] = useState<Record<string, DocumentStatus>>({})
  const [uploading, setUploading] = useState(false)
  const [showSidebar, setShowSidebar] = useState(() => window.innerWidth >= 900)
  const [showChat, setShowChat] = useState(() => window.innerWidth >= 1100)
  const [overrideLeft, setOverrideLeft] = useState<OverridePdf>(null)
  const [overrideRight, setOverrideRight] = useState<OverridePdf>(null)
  const [projectOpen, setProjectOpen] = useState(false)
  const [projectArchive, setProjectArchive] = useState<File | null>(null)
  const [profileOpen, setProfileOpen] = useState(!user.settings.api_key_configured)
  const [editTexOpen, setEditTexOpen] = useState(false)
  const [theme, setTheme] = useState<UserSettings['theme']>(user.settings.theme)
  const [visionEnabled, setVisionEnabled] = useState(user.settings.vision_enabled)
  const [visionMode, setVisionMode] = useState<UserSettings['vision_mode']>(user.settings.vision_mode)
  const [favorites, setFavorites] = useState<string[]>(user.settings.favorites)
  const [literatureChatOpen, setLiteratureChatOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [pollRevision, setPollRevision] = useState(0)
  const [annotations, setAnnotations] = useState<AnnotationItem[]>([])
  const [structureOutline, setStructureOutline] = useState<OutlineItem[] | null>(null)
  const [structureFigures, setStructureFigures] = useState<FigureItem[]>([])
  const [syncScroll, setSyncScroll] = useState(true)
  const [pendingQuote, setPendingQuote] = useState<PendingQuote>(null)
  const [pendingLocate, setPendingLocate] = useState<PendingLocate>(null)
  const [activePane, setActivePane] = useState<PaneSide>('original')

  const pollTimerRef = useRef<number | null>(null)
  const originalPaneRef = useRef<PdfPaneHandle | null>(null)
  const translatedPaneRef = useRef<PdfPaneHandle | null>(null)
  const emptyUploadRef = useRef<HTMLInputElement | null>(null)
  const syncLockRef = useRef<{ side: PaneSide; until: number }>({ side: 'original', until: 0 })

  useEffect(() => {
    setTheme(user.settings.theme)
    setVisionEnabled(user.settings.vision_enabled)
    setVisionMode(user.settings.vision_mode)
    setFavorites(user.settings.favorites)
  }, [user])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 900) setShowSidebar(false)
      if (window.innerWidth < 1100) setShowChat(false)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const persistPreferences = useCallback(async (payload: Partial<UserSettings>) => {
    try {
      const nextSettings = await updateSettings(payload)
      onUserChange({ ...user, settings: nextSettings })
    } catch (e: any) {
      setNotice(`偏好保存失败：${e?.message || String(e)}`)
    }
  }, [onUserChange, user])

  const cycleVision = useCallback(() => {
    let nextEnabled = visionEnabled
    let nextMode = visionMode
    if (!visionEnabled) {
      nextEnabled = true
      nextMode = 'auto'
    } else if (visionMode === 'auto') {
      nextMode = 'manual'
    } else {
      nextEnabled = false
    }
    setVisionEnabled(nextEnabled)
    setVisionMode(nextMode)
    void persistPreferences({ vision_enabled: nextEnabled, vision_mode: nextMode })
  }, [persistPreferences, visionEnabled, visionMode])

  const refreshActive = useCallback(() => {
    if (!activeId) return
    void getDocumentStatus(activeId)
      .then((d) => setDocCache((c) => ({ ...c, [activeId]: d })))
      .catch((e) => console.error(e))
  }, [activeId])

  const refreshSummaries = useCallback(async () => {
    try {
      const list = await listDocuments()
      setSummaries(list)
      return list
    } catch (e: any) {
      if (e?.status === 401) onLogout()
      else console.error(e)
      return []
    }
  }, [onLogout])

  useEffect(() => {
    void (async () => {
      const list = await refreshSummaries()
      if (list.length > 0) {
        setActiveId((prev) => prev && list.some((item) => item.document_id === prev) ? prev : list[0].document_id)
      }
    })()
  }, [refreshSummaries])

  useEffect(() => {
    if (pollTimerRef.current) {
      window.clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
    if (!activeId) return

    const fetchOnce = async () => {
      try {
        const data = await getDocumentStatus(activeId)
        setDocCache((c) => ({ ...c, [activeId]: data }))
        setSummaries((prev) =>
          prev.map((s) =>
            s.document_id === activeId
              ? {
                  ...s,
                  status: data.status,
                  has_translated_pdf: !!data.translated_pdf_url,
                  updated_at: data.updated_at,
                  last_opened_at: data.last_opened_at
                }
              : s
          )
        )
        if (data.status === 'done' || data.status === 'failed') {
          if (pollTimerRef.current) {
            window.clearInterval(pollTimerRef.current)
            pollTimerRef.current = null
          }
        }
      } catch (e: any) {
        if (e?.status === 401) onLogout()
        else console.error(e)
      }
    }
    void fetchOnce()
    pollTimerRef.current = window.setInterval(fetchOnce, 1500)
    return () => {
      if (pollTimerRef.current) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [activeId, onLogout, pollRevision])

  const activeDoc: DocumentStatus | undefined = activeId ? docCache[activeId] : undefined
  const originalPdfUrl = activeDoc?.original_pdf_url ? makeDataUrl(activeDoc.original_pdf_url) : undefined
  const translatedPdfUrl = activeDoc?.translated_pdf_url ? makeDataUrl(activeDoc.translated_pdf_url) : undefined

  const handleRetry = useCallback(async () => {
    if (!activeId || retrying) return
    setRetrying(true)
    try {
      const queued = await retryDocument(activeId)
      setDocCache((cache) => ({
        ...cache,
        [activeId]: cache[activeId]
          ? { ...cache[activeId], status: queued.status, current_stage_label: `等待从 ${queued.resume_from} 恢复` }
          : cache[activeId]
      }))
      setSummaries((items) => items.map((item) => (
        item.document_id === activeId ? { ...item, status: 'queued' } : item
      )))
      setPollRevision((value) => value + 1)
    } catch (error: any) {
      setNotice(`重试失败：${error?.message ?? String(error)}`)
    } finally {
      setRetrying(false)
    }
  }, [activeId, retrying])

  useEffect(() => {
    setOverrideLeft(null)
    setOverrideRight(null)
    setAnnotations([])
    setStructureOutline(null)
    setStructureFigures([])
    setPendingQuote(null)
  }, [activeId])

  // Annotations and the document structure (backend outline + figure gallery)
  // are per-document; reload them whenever the active document changes and
  // again once its pipeline finishes.
  const annotationsDocIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (!activeId || activeDoc?.status !== 'done') return
    if (annotationsDocIdRef.current === activeId) return
    annotationsDocIdRef.current = activeId
    void listAnnotations(activeId).then(setAnnotations).catch((e) => console.error(e))
    void getDocumentStructure(activeId)
      .then((structure) => {
        setStructureOutline(structure.outline?.length ? structure.outline : null)
        setStructureFigures(
          (structure.figures || []).map((figure) => ({ ...figure, url: makeDataUrl(figure.url) }))
        )
      })
      .catch((e) => console.error(e))
  }, [activeId, activeDoc?.status])

  const handleCreateAnnotation = useCallback(async (payload: {
    page: number
    quote: string
    color: string
    note: string
    positionRatio: number
  }) => {
    if (!activeId) return
    try {
      await createAnnotation(activeId, {
        page: payload.page,
        quote: payload.quote,
        color: payload.color,
        note: payload.note,
        position_ratio: payload.positionRatio
      })
      setAnnotations(await listAnnotations(activeId))
    } catch (e: any) {
      setNotice(`批注保存失败：${e?.message ?? String(e)}`)
    }
  }, [activeId])

  const handleDeleteAnnotation = useCallback(async (id: string) => {
    if (!activeId) return
    try {
      await deleteAnnotation(activeId, id)
      setAnnotations((prev) => prev.filter((item) => item.id !== id))
    } catch (e: any) {
      setNotice(`批注删除失败：${e?.message ?? String(e)}`)
    }
  }, [activeId])

  const handleExportNotes = useCallback(() => {
    if (!activeId) return
    void downloadNotes(activeId).catch((e: any) => setNotice(`导出笔记失败：${e?.message ?? String(e)}`))
  }, [activeId])

  const handleProgressChange = useCallback((page: number, ratio: number) => {
    if (!activeId) return
    void updateReadingProgress(activeId, page, ratio).catch(() => {})
  }, [activeId])

  const handlePaneScrollRatio = useCallback((side: PaneSide, ratio: number) => {
    if (!syncScroll) return
    const now = Date.now()
    if (syncLockRef.current.side === side && now < syncLockRef.current.until) return
    const target = side === 'original' ? translatedPaneRef.current : originalPaneRef.current
    if (!target) return
    syncLockRef.current = { side: side === 'original' ? 'translated' : 'original', until: now + 600 }
    target.scrollToRatio(ratio)
  }, [syncScroll])

  const handleAskAI = useCallback((_side: PaneSide, payload: { selectedText: string }) => {
    setShowChat(true)
    setLiteratureChatOpen(false)
    setPendingQuote({ text: payload.selectedText, nonce: Date.now() })
  }, [])

  // Ctrl/Cmd+F opens in-document search on the pane the user last touched.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'f') return
      event.preventDefault()
      const pane = activePane === 'original' ? originalPaneRef.current : translatedPaneRef.current
      pane?.openSearch()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [activePane])

  const handleLocateCounterpart = useCallback(async (
    sourceSide: 'original' | 'translated',
    payload: { selectedText: string; page: number; pageCount: number }
  ) => {
    if (!activeId) return
    try {
      const located = await locateCounterpart({
        documentId: activeId,
        source_side: sourceSide,
        selected_text: payload.selectedText,
        source_page: payload.page,
        source_page_count: payload.pageCount,
      })
      const target = sourceSide === 'original' ? translatedPaneRef.current : originalPaneRef.current
      await target?.locateAndHighlight({
        text: located.target_text,
        highlightText: located.highlight_text,
        positionRatio: located.position_ratio,
      })
    } catch (e: any) {
      alert(`未能定位对应内容：${e?.message ?? String(e)}`)
    }
  }, [activeId])

  // A library-search hit opens its document and highlights the matched text
  // once the document is available.
  useEffect(() => {
    if (!pendingLocate || !activeDoc || activeDoc.status !== 'done') return
    const { text, side } = pendingLocate
    setPendingLocate(null)
    void handleLocateCounterpart(side === 'original' ? 'translated' : 'original', {
      selectedText: text,
      page: 1,
      pageCount: 1,
    })
  }, [pendingLocate, activeDoc, handleLocateCounterpart])

  // Chat citation badge: jump to the cited passage, switching documents if
  // the citation points at another paper in the library.
  const handleCitationJump = useCallback((source: SourceRefItem) => {
    if (!source.document_id) return
    const snippet = source.content.slice(0, 400)
    if (source.document_id === activeId) {
      void handleLocateCounterpart('translated', { selectedText: snippet, page: 1, pageCount: 1 })
      return
    }
    setActiveId(source.document_id)
    setLiteratureChatOpen(false)
    setPendingLocate({ text: snippet, side: 'original' })
  }, [activeId, handleLocateCounterpart])

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true)
    try {
      const result = await uploadFile(file, { visionCheckEnabled: visionEnabled, visionCheckMode: visionMode })
      setActiveId(result.document_id)
      setLiteratureChatOpen(false)
      await refreshSummaries()
    } catch (e: any) {
      if (e?.code === 'config_required') setProfileOpen(true)
      setNotice(`上传失败：${e?.message ?? String(e)}`)
    } finally {
      setUploading(false)
    }
  }, [refreshSummaries, visionEnabled, visionMode])

  const handleIncomingFile = useCallback((file: File) => {
    if (/\.(?:zip|tar|tar\.gz|tgz)$/i.test(file.name)) {
      setProjectArchive(file)
      setProjectOpen(true)
      return
    }
    void handleUpload(file)
  }, [handleUpload])

  const handleProjectBuilt = useCallback(async (documentId: string) => {
    setActiveId(documentId)
    await refreshSummaries()
  }, [refreshSummaries])

  const handleToggleFavorite = useCallback((docId: string) => {
    const next = favorites.includes(docId) ? favorites.filter((x) => x !== docId) : [...favorites, docId]
    setFavorites(next)
    void persistPreferences({ favorites: next })
  }, [favorites, persistPreferences])

  const handleDelete = useCallback(async (docId: string) => {
    if (!window.confirm('删除这条历史记录？对应文件不会从系统默认输出目录移除。')) return
    try {
      await deleteDocument(docId)
      setDocCache((prev) => {
        const next = { ...prev }
        delete next[docId]
        return next
      })
      const nextFavorites = favorites.filter((item) => item !== docId)
      setFavorites(nextFavorites)
      void persistPreferences({ favorites: nextFavorites })
      setSummaries((prev) => prev.filter((item) => item.document_id !== docId))
      setActiveId((prev) => (prev === docId ? undefined : prev))
    } catch (e: any) {
      alert(`删除失败：${e?.message ?? String(e)}`)
    }
  }, [favorites, persistPreferences])

  const handleRename = useCallback(async (documentId: string, name: string) => {
    try {
      const updated = await renameDocument(documentId, name)
      setDocCache((cache) => ({ ...cache, [documentId]: updated }))
      await refreshSummaries()
    } catch (e: any) {
      alert(`重命名失败：${e?.message ?? String(e)}`)
    }
  }, [refreshSummaries])

  const handleOpenInPane = useCallback((artifact: ArtifactItem) => {
    if (!artifact.url) return
    setOverrideRight({ url: makeDataUrl(artifact.url), name: artifact.name })
  }, [])

  const handleLogout = useCallback(async () => {
    try {
      await logout()
    } catch (e) {
      console.error(e)
    } finally {
      onLogout()
    }
  }, [onLogout])

  const chatRefs = activeDoc?.references ?? []
  const artifacts = activeDoc?.artifacts ?? []
  const logs = activeDoc?.logs ?? []
  const stages = activeDoc?.stages ?? []
  const pendingReviews = activeDoc?.pending_reviews ?? []

  const sourceTitle = useMemo(() => {
    if (!activeDoc) return '原始 PDF'
    return `原始 · ${activeDoc.source_filename || activeDoc.document_id}`
  }, [activeDoc])

  const translatedName = translatedPdfName(activeDoc?.source_filename || 'document.pdf')

  return (
    <div className="app-shell">
      {notice && <div className="app-notice" role="alert"><AlertCircle size={16} /><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice(null)}>×</button></div>}
      {showSidebar ? (
        <Sidebar
          user={user}
          documents={summaries}
          activeDocumentId={activeId}
          favorites={favorites}
          uploading={uploading}
          artifacts={artifacts}
          logs={logs}
          theme={theme}
          chatVisible={showChat}
          visionEnabled={visionEnabled}
          visionMode={visionMode}
          activeStatus={activeDoc?.status}
          onUpload={handleIncomingFile}
          onSelect={(id) => {
            setActiveId(id)
            setLiteratureChatOpen(false)
          }}
          onToggleFavorite={handleToggleFavorite}
          onDelete={handleDelete}
          onRename={(id, name) => void handleRename(id, name)}
          onCollapse={() => setShowSidebar(false)}
          onOpenInPane={handleOpenInPane}
          onEditTex={() => setEditTexOpen(true)}
          onNewProject={() => {
            setProjectArchive(null)
            setProjectOpen(true)
          }}
          onOpenProfile={() => setProfileOpen(true)}
          onLogout={() => void handleLogout()}
          onToggleChat={() => setShowChat((v) => !v)}
          onToggleVision={cycleVision}
          onToggleTheme={() => {
            const next = theme === 'dark' ? 'light' : 'dark'
            setTheme(next)
            void persistPreferences({ theme: next })
          }}
          onRefreshStatus={refreshActive}
          onOpenLiteratureChat={() => setLiteratureChatOpen(true)}
          literatureChatOpen={literatureChatOpen}
          onSearchLocate={(hit) => {
            if (hit.document_id !== activeId) {
              setActiveId(hit.document_id)
              setLiteratureChatOpen(false)
            }
            setPendingLocate({ text: hit.snippet, side: hit.side })
          }}
        />
      ) : (
        <button
          className="sidebar-expand-btn"
          title="打开侧栏"
          onClick={() => setShowSidebar(true)}
        >
          <PanelLeftOpen size={18} />
        </button>
      )}

      <main className="workspace">
        {literatureChatOpen ? (
          <LiteratureChatPage
            documents={summaries}
            onClose={() => setLiteratureChatOpen(false)}
          />
        ) : (
        <>
        {activeDoc && (
          <ProgressBar
            status={activeDoc.status}
            progress={activeDoc.progress}
            currentStageLabel={activeDoc.current_stage_label}
            etaSeconds={activeDoc.eta_seconds}
            stages={stages}
            failure={activeDoc.failure}
            latexRecovery={activeDoc.latex_recovery}
            retrying={retrying}
            onRetry={handleRetry}
          />
        )}
        {!activeId ? (
          <div className="workspace-empty">
            <div className="empty-illustration"><UploadCloud size={32} /></div>
            <span className="eyebrow">你的本地论文工作台</span>
            <h2>欢迎回来，{user.username}</h2>
            <p className="muted">上传 PDF 或 LaTeX，PaperReader 会保留原文排版并生成可对照阅读的译文。</p>
            <div className="latex-recommendation">arXiv 或论文提供 LaTeX 源码时，优先上传 LaTeX，可获得更好的结构与翻译质量。</div>
            <input ref={emptyUploadRef} type="file" accept=".pdf,.tex,.zip,.tar,.tar.gz,.tgz" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) handleIncomingFile(file); event.currentTarget.value = '' }} />
            <div className="empty-actions"><button className="btn primary" disabled={uploading} onClick={() => emptyUploadRef.current?.click()}>{uploading ? '正在上传…' : '选择论文'}</button><button className="btn" onClick={() => { setProjectArchive(null); setProjectOpen(true) }}>导入 TeX 项目</button></div>
            {!user.settings.api_key_configured && <button className="config-callout" onClick={() => setProfileOpen(true)}><AlertCircle size={16} />开始前需要配置 AI 服务</button>}
          </div>
        ) : (
          <>
          <PanelGroup direction="horizontal" autoSaveId="paperreader.layout">
            <Panel defaultSize={showChat ? 35 : 50} minSize={20}>
              <PdfPane
                ref={originalPaneRef}
                title={sourceTitle}
                pdfUrl={originalPdfUrl}
                overrideUrl={overrideLeft?.url}
                overrideTitle={overrideLeft ? `产物 · ${overrideLeft.name}` : undefined}
                onAcceptDrop={({ url, name }) => setOverrideLeft({ url, name })}
                onClearOverride={() => setOverrideLeft(null)}
                downloadName={activeDoc?.source_filename}
                counterpartLabel="右侧译文"
                onLocateCounterpart={(payload) => void handleLocateCounterpart('original', payload)}
                onAskAI={(payload) => handleAskAI('original', payload)}
                annotations={annotations}
                onCreateAnnotation={handleCreateAnnotation}
                onDeleteAnnotation={handleDeleteAnnotation}
                onExportNotes={handleExportNotes}
                initialPosition={activeDoc ? { page: activeDoc.last_read_page, ratio: activeDoc.last_read_ratio } : null}
                onProgressChange={handleProgressChange}
                onUserScrollRatio={(ratio) => handlePaneScrollRatio('original', ratio)}
                syncEnabled={syncScroll}
                onToggleSync={() => setSyncScroll((v) => !v)}
                figures={structureFigures}
                outline={structureOutline}
                onActivate={() => setActivePane('original')}
              />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel defaultSize={showChat ? 35 : 50} minSize={20}>
              <PdfPane
                ref={translatedPaneRef}
                title={`译文 · ${translatedName}`}
                pdfUrl={translatedPdfUrl}
                overrideUrl={overrideRight?.url}
                overrideTitle={overrideRight ? `产物 · ${overrideRight.name}` : undefined}
                onAcceptDrop={({ url, name }) => setOverrideRight({ url, name })}
                onClearOverride={() => setOverrideRight(null)}
                downloadName={translatedName}
                counterpartLabel="左侧原文"
                onLocateCounterpart={(payload) => void handleLocateCounterpart('translated', payload)}
                onAskAI={(payload) => handleAskAI('translated', payload)}
                annotations={annotations}
                onCreateAnnotation={handleCreateAnnotation}
                onDeleteAnnotation={handleDeleteAnnotation}
                onExportNotes={handleExportNotes}
                initialPosition={activeDoc ? { page: activeDoc.last_read_page, ratio: activeDoc.last_read_ratio } : null}
                onProgressChange={handleProgressChange}
                onUserScrollRatio={(ratio) => handlePaneScrollRatio('translated', ratio)}
                syncEnabled={syncScroll}
                onToggleSync={() => setSyncScroll((v) => !v)}
                figures={structureFigures}
                outline={structureOutline}
                onActivate={() => setActivePane('translated')}
              />
            </Panel>
            {showChat && (
              <>
                <PanelResizeHandle className="resize-handle" />
                <Panel defaultSize={30} minSize={20}>
                  <ChatPanel
                    documentId={activeId}
                    references={chatRefs}
                    onCollapse={() => setShowChat(false)}
                    pendingQuote={pendingQuote}
                    onQuoteConsumed={() => setPendingQuote(null)}
                    onCitationJump={handleCitationJump}
                  />
                </Panel>
              </>
            )}
          </PanelGroup>
          {!showChat && (
            <button
              className="chat-expand-btn"
              aria-label="展开 AI Chat"
              title="展开 AI 对话"
              onClick={() => setShowChat(true)}
            >
              <PanelRightOpen size={18} />
            </button>
          )}
          </>
        )}
        </>
        )}
      </main>

      <ProjectDrawer
        open={projectOpen}
        onClose={() => {
          setProjectOpen(false)
          setProjectArchive(null)
        }}
        onBuilt={(id) => void handleProjectBuilt(id)}
        visionCheckEnabled={visionEnabled}
        visionCheckMode={visionMode}
        initialArchive={projectArchive}
        onArchiveConsumed={() => setProjectArchive(null)}
      />
      <ProfileModal
        open={profileOpen}
        user={user}
        onClose={() => setProfileOpen(false)}
        onUserChange={onUserChange}
      />
      {activeId && activeDoc?.status === 'awaiting_review' && pendingReviews.length > 0 && (
        <ReviewModal
          documentId={activeId}
          proposals={pendingReviews}
          onResolved={() => {
            void getDocumentStatus(activeId).then((d) => setDocCache((c) => ({ ...c, [activeId]: d })))
          }}
        />
      )}
      {activeId && editTexOpen && (
        <TexEditorModal
          documentId={activeId}
          onClose={() => setEditTexOpen(false)}
          onCompiled={() => {
            void getDocumentStatus(activeId).then((d) => setDocCache((c) => ({ ...c, [activeId]: d })))
          }}
        />
      )}
    </div>
  )
}
