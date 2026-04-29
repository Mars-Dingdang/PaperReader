import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { PanelLeftOpen } from 'lucide-react'
import { ChatPanel } from '../components/ChatPanel'
import { PdfPane } from '../components/PdfPane'
import { ProgressBar } from '../components/ProgressBar'
import { ProjectDrawer } from '../components/ProjectDrawer'
import { ReviewModal } from '../components/ReviewModal'
import { Sidebar } from '../components/Sidebar'
import { TexEditorModal } from '../components/TexEditorModal'
import type { ArtifactItem, DocumentStatus, DocumentSummary } from '../lib/api'
import {
  getDocumentStatus,
  listDocuments,
  makeDataUrl,
  sendChat,
  uploadFile
} from '../lib/api'

const FAV_LS_KEY = 'paperreader.favorites'
const VISION_LS_KEY = 'paperreader.vision'
const THEME_LS_KEY = 'paperreader.theme'

type OverridePdf = { url: string; name: string } | null
type Theme = 'light' | 'dark'

export function ReaderPage() {
  const [summaries, setSummaries] = useState<DocumentSummary[]>([])
  const [activeId, setActiveId] = useState<string | undefined>(undefined)
  const [docCache, setDocCache] = useState<Record<string, DocumentStatus>>({})
  const [uploading, setUploading] = useState(false)
  const [favorites, setFavorites] = useState<string[]>([])
  const [showSidebar, setShowSidebar] = useState(true)
  const [showChat, setShowChat] = useState(true)
  const [overrideLeft, setOverrideLeft] = useState<OverridePdf>(null)
  const [overrideRight, setOverrideRight] = useState<OverridePdf>(null)
  const [projectOpen, setProjectOpen] = useState(false)
  const [editTexOpen, setEditTexOpen] = useState(false)
  const [visionEnabled, setVisionEnabled] = useState(true)
  const [visionMode, setVisionMode] = useState<'auto' | 'manual'>('auto')
  const [theme, setTheme] = useState<Theme>('light')

  const pollTimerRef = useRef<number | null>(null)

  // Load preferences
  useEffect(() => {
    try {
      const raw = localStorage.getItem(FAV_LS_KEY)
      if (raw) setFavorites(JSON.parse(raw))
    } catch {}
    try {
      const raw = localStorage.getItem(VISION_LS_KEY)
      if (raw) {
        const v = JSON.parse(raw)
        setVisionEnabled(!!v.enabled)
        setVisionMode(v.mode === 'manual' ? 'manual' : 'auto')
      }
    } catch {}
    try {
      const raw = localStorage.getItem(THEME_LS_KEY)
      if (raw === 'dark' || raw === 'light') {
        setTheme(raw)
      } else if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
        setTheme('dark')
      }
    } catch {}
  }, [])
  useEffect(() => {
    try {
      localStorage.setItem(FAV_LS_KEY, JSON.stringify(favorites))
    } catch {}
  }, [favorites])
  useEffect(() => {
    try {
      localStorage.setItem(VISION_LS_KEY, JSON.stringify({ enabled: visionEnabled, mode: visionMode }))
    } catch {}
  }, [visionEnabled, visionMode])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem(THEME_LS_KEY, theme) } catch {}
  }, [theme])

  const cycleVision = useCallback(() => {
    if (!visionEnabled) { setVisionEnabled(true); setVisionMode('auto') }
    else if (visionMode === 'auto') setVisionMode('manual')
    else setVisionEnabled(false)
  }, [visionEnabled, visionMode])

  const refreshActive = useCallback(() => {
    if (!activeId) return
    void getDocumentStatus(activeId).then((d) => setDocCache((c) => ({ ...c, [activeId]: d })))
  }, [activeId])

  const refreshSummaries = useCallback(async () => {
    try {
      const list = await listDocuments()
      setSummaries(list)
      return list
    } catch (e) {
      console.error(e)
      return []
    }
  }, [])

  // Initial load
  useEffect(() => {
    void (async () => {
      const list = await refreshSummaries()
      if (list.length > 0 && !activeId) {
        setActiveId(list[0].document_id)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Poll active document
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
              ? { ...s, status: data.status, has_translated_pdf: !!data.translated_pdf_url }
              : s
          )
        )
        if (data.status === 'done' || data.status === 'failed') {
          if (pollTimerRef.current) {
            window.clearInterval(pollTimerRef.current)
            pollTimerRef.current = null
          }
        }
      } catch (e) {
        console.error(e)
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
  }, [activeId])

  const activeDoc: DocumentStatus | undefined = activeId ? docCache[activeId] : undefined

  const originalPdfUrl = activeDoc?.original_pdf_url ? makeDataUrl(activeDoc.original_pdf_url) : undefined
  const translatedPdfUrl = activeDoc?.translated_pdf_url ? makeDataUrl(activeDoc.translated_pdf_url) : undefined

  // Reset overrides when switching active doc
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

  const handleOpenInPane = useCallback((artifact: ArtifactItem) => {
    if (!artifact.url) return
    setOverrideRight({ url: makeDataUrl(artifact.url), name: artifact.name })
  }, [])

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
          onCollapse={() => setShowSidebar(false)}
          onOpenInPane={handleOpenInPane}
          onEditTex={() => setEditTexOpen(true)}
          onNewProject={() => setProjectOpen(true)}
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
            <h2>欢迎使用 PaperReader</h2>
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
      {activeId && activeDoc?.status === 'awaiting_review' && pendingReviews.length > 0 && (
        <ReviewModal
          documentId={activeId}
          proposals={pendingReviews}
          onResolved={() => {
            // trigger an immediate refresh
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
