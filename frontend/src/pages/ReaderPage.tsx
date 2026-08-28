import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { PanelLeftOpen } from 'lucide-react'
import { ChatPanel } from '../components/ChatPanel'
import { PdfPane } from '../components/PdfPane'
import { ProgressBar } from '../components/ProgressBar'
import { ProfileModal } from '../components/ProfileModal'
import { ProjectDrawer } from '../components/ProjectDrawer'
import { ReviewModal } from '../components/ReviewModal'
import { Sidebar } from '../components/Sidebar'
import { TexEditorModal } from '../components/TexEditorModal'
import type { ArtifactItem, AuthUser, DocumentStatus, DocumentSummary, UserSettings } from '../lib/api'
import {
  deleteDocument,
  getDocumentStatus,
  listDocuments,
  logout,
  makeDataUrl,
  sendChat,
  updateSettings,
  uploadFile
} from '../lib/api'

type OverridePdf = { url: string; name: string } | null

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
  const [showSidebar, setShowSidebar] = useState(true)
  const [showChat, setShowChat] = useState(true)
  const [overrideLeft, setOverrideLeft] = useState<OverridePdf>(null)
  const [overrideRight, setOverrideRight] = useState<OverridePdf>(null)
  const [projectOpen, setProjectOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [editTexOpen, setEditTexOpen] = useState(false)
  const [settingsLoaded, setSettingsLoaded] = useState(false)
  const [theme, setTheme] = useState<UserSettings['theme']>(user.settings.theme)
  const [visionEnabled, setVisionEnabled] = useState(user.settings.vision_enabled)
  const [visionMode, setVisionMode] = useState<UserSettings['vision_mode']>(user.settings.vision_mode)
  const [favorites, setFavorites] = useState<string[]>(user.settings.favorites)

  const pollTimerRef = useRef<number | null>(null)

  useEffect(() => {
    setTheme(user.settings.theme)
    setVisionEnabled(user.settings.vision_enabled)
    setVisionMode(user.settings.vision_mode)
    setFavorites(user.settings.favorites)
    setSettingsLoaded(true)
  }, [user])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (!settingsLoaded) return
    void (async () => {
      try {
        const nextSettings = await updateSettings({
          theme,
          vision_enabled: visionEnabled,
          vision_mode: visionMode,
          favorites
        })
        onUserChange({ ...user, settings: nextSettings })
      } catch (e) {
        console.error(e)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, visionEnabled, visionMode, favorites])

  const cycleVision = useCallback(() => {
    if (!visionEnabled) {
      setVisionEnabled(true)
      setVisionMode('auto')
    } else if (visionMode === 'auto') {
      setVisionMode('manual')
    } else {
      setVisionEnabled(false)
    }
  }, [visionEnabled, visionMode])

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
  }, [activeId, onLogout])

  const activeDoc: DocumentStatus | undefined = activeId ? docCache[activeId] : undefined
  const originalPdfUrl = activeDoc?.original_pdf_url ? makeDataUrl(activeDoc.original_pdf_url) : undefined
  const translatedPdfUrl = activeDoc?.translated_pdf_url ? makeDataUrl(activeDoc.translated_pdf_url) : undefined

  useEffect(() => {
    setOverrideLeft(null)
    setOverrideRight(null)
  }, [activeId])

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true)
    try {
      const result = await uploadFile(file, { visionCheckEnabled: visionEnabled, visionCheckMode: visionMode })
      setActiveId(result.document_id)
      await refreshSummaries()
    } catch (e: any) {
      alert(`上传失败：${e?.message ?? String(e)}`)
    } finally {
      setUploading(false)
    }
  }, [refreshSummaries, visionEnabled, visionMode])

  const handleProjectBuilt = useCallback(async (documentId: string) => {
    setActiveId(documentId)
    await refreshSummaries()
  }, [refreshSummaries])

  const handleToggleFavorite = useCallback((docId: string) => {
    setFavorites((prev) =>
      prev.includes(docId) ? prev.filter((x) => x !== docId) : [...prev, docId]
    )
  }, [])

  const handleDeleteDocument = useCallback(async (docId: string) => {
    if (!window.confirm('删除这条历史记录？对应文件不会从系统默认输出目录移除。')) return
    try {
      await deleteDocument(docId)
      setDocCache((prev) => {
        const next = { ...prev }
        delete next[docId]
        return next
      })
      setFavorites((prev) => prev.filter((item) => item !== docId))
      setSummaries((prev) => prev.filter((item) => item.document_id !== docId))
      setActiveId((prev) => (prev === docId ? undefined : prev))
    } catch (e) {
      console.error(e)
    }
  }, [])

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

  return (
    <div className="app-shell">
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
          onUpload={(f) => void handleUpload(f)}
          onSelect={setActiveId}
          onToggleFavorite={handleToggleFavorite}
          onDeleteDocument={handleDeleteDocument}
          onCollapse={() => setShowSidebar(false)}
          onOpenInPane={handleOpenInPane}
          onEditTex={() => setEditTexOpen(true)}
          onNewProject={() => setProjectOpen(true)}
          onOpenProfile={() => setProfileOpen(true)}
          onLogout={() => void handleLogout()}
          onToggleChat={() => setShowChat((v) => !v)}
          onToggleVision={cycleVision}
          onToggleTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          onRefreshStatus={refreshActive}
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
        {activeDoc && (
          <ProgressBar
            status={activeDoc.status}
            progress={activeDoc.progress}
            currentStageLabel={activeDoc.current_stage_label}
            etaSeconds={activeDoc.eta_seconds}
            stages={stages}
          />
        )}
        {!activeId ? (
          <div className="workspace-empty">
            <h2>欢迎回来，{user.username}</h2>
            <p className="muted">点击左侧「新解析」上传 PDF 或 TeX 文件开始</p>
          </div>
        ) : (
          <PanelGroup direction="horizontal" autoSaveId="paperreader.layout">
            <Panel defaultSize={showChat ? 35 : 50} minSize={20}>
              <PdfPane
                title={sourceTitle}
                pdfUrl={originalPdfUrl}
                overrideUrl={overrideLeft?.url}
                overrideTitle={overrideLeft ? `产物 · ${overrideLeft.name}` : undefined}
                onAcceptDrop={({ url, name }) => setOverrideLeft({ url, name })}
                onClearOverride={() => setOverrideLeft(null)}
              />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel defaultSize={showChat ? 35 : 50} minSize={20}>
              <PdfPane
                title="译文 PDF"
                pdfUrl={translatedPdfUrl}
                overrideUrl={overrideRight?.url}
                overrideTitle={overrideRight ? `产物 · ${overrideRight.name}` : undefined}
                onAcceptDrop={({ url, name }) => setOverrideRight({ url, name })}
                onClearOverride={() => setOverrideRight(null)}
              />
            </Panel>
            {showChat && (
              <>
                <PanelResizeHandle className="resize-handle" />
                <Panel defaultSize={30} minSize={20}>
                  <ChatPanel
                    documentId={activeId}
                    references={chatRefs}
                    onSend={async ({ message, override_api_key, override_base_url, override_model }) => {
                      const resp = await sendChat({
                        document_id: activeId,
                        message,
                        override_api_key,
                        override_base_url,
                        override_model
                      })
                      return resp.answer
                    }}
                  />
                </Panel>
              </>
            )}
          </PanelGroup>
        )}
      </main>

      <ProjectDrawer
        open={projectOpen}
        onClose={() => setProjectOpen(false)}
        onBuilt={(id) => void handleProjectBuilt(id)}
        visionCheckEnabled={visionEnabled}
        visionCheckMode={visionMode}
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
