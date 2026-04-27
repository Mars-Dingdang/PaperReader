import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { MessageSquareText, PanelLeftOpen, ScrollText } from 'lucide-react'
import { ChatPanel } from '../components/ChatPanel'
import { PdfPane } from '../components/PdfPane'
import { Sidebar } from '../components/Sidebar'
import type { DocumentStatus, DocumentSummary } from '../lib/api'
import {
  getDocumentStatus,
  listDocuments,
  makeDataUrl,
  sendChat,
  uploadFile
} from '../lib/api'

const FAV_LS_KEY = 'paperreader.favorites'

export function ReaderPage() {
  const [summaries, setSummaries] = useState<DocumentSummary[]>([])
  const [activeId, setActiveId] = useState<string | undefined>(undefined)
  const [docCache, setDocCache] = useState<Record<string, DocumentStatus>>({})
  const [uploading, setUploading] = useState(false)
  const [favorites, setFavorites] = useState<string[]>([])
  const [showSidebar, setShowSidebar] = useState(true)
  const [showChat, setShowChat] = useState(true)

  const pollTimerRef = useRef<number | null>(null)

  // Load favorites
  useEffect(() => {
    try {
      const raw = localStorage.getItem(FAV_LS_KEY)
      if (raw) setFavorites(JSON.parse(raw))
    } catch {}
  }, [])
  useEffect(() => {
    try {
      localStorage.setItem(FAV_LS_KEY, JSON.stringify(favorites))
    } catch {}
  }, [favorites])

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
        // also update summary for status
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

  const handleUpload = useCallback(async (file: File) => {
    setUploading(true)
    try {
      const result = await uploadFile(file)
      setActiveId(result.document_id)
      await refreshSummaries()
    } catch (e: any) {
      alert(`上传失败：${e?.message ?? String(e)}`)
    } finally {
      setUploading(false)
    }
  }, [refreshSummaries])

  const handleToggleFavorite = useCallback((docId: string) => {
    setFavorites((prev) =>
      prev.includes(docId) ? prev.filter((x) => x !== docId) : [...prev, docId]
    )
  }, [])

  const chatRefs = activeDoc?.references ?? []
  const artifacts = activeDoc?.artifacts ?? []
  const logs = activeDoc?.logs ?? []

  const sourceTitle = useMemo(() => {
    if (!activeDoc) return '原始 PDF'
    return `原始 · ${activeDoc.source_filename || activeDoc.document_id}`
  }, [activeDoc])

  return (
    <div className="app-shell">
      {showSidebar && (
        <Sidebar
          documents={summaries}
          activeDocumentId={activeId}
          favorites={favorites}
          uploading={uploading}
          artifacts={artifacts}
          logs={logs}
          onUpload={(f) => void handleUpload(f)}
          onSelect={setActiveId}
          onToggleFavorite={handleToggleFavorite}
          onCollapse={() => setShowSidebar(false)}
        />
      )}

      <div className="rail">
        {!showSidebar && (
          <button className="rail-btn" title="打开侧栏" onClick={() => setShowSidebar(true)}>
            <PanelLeftOpen size={18} />
          </button>
        )}
        <button
          className={`rail-btn ${showChat ? 'active' : ''}`}
          title={showChat ? '关闭对话' : '打开对话'}
          onClick={() => setShowChat((v) => !v)}
        >
          <MessageSquareText size={18} />
        </button>
        <div className="rail-spacer" />
        <button
          className="rail-btn"
          title={`状态：${activeDoc?.status ?? '—'}`}
          onClick={() => activeId && void getDocumentStatus(activeId).then((d) => setDocCache((c) => ({ ...c, [activeId]: d })))}
        >
          <ScrollText size={18} />
        </button>
      </div>

      <main className="workspace">
        {!activeId ? (
          <div className="workspace-empty">
            <h2>欢迎使用 PaperReader</h2>
            <p className="muted">点击左侧「新解析」上传 PDF 或 TeX 文件开始</p>
          </div>
        ) : (
          <PanelGroup direction="horizontal" autoSaveId="paperreader.layout">
            <Panel defaultSize={showChat ? 35 : 50} minSize={20}>
              <PdfPane title={sourceTitle} pdfUrl={originalPdfUrl} />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel defaultSize={showChat ? 35 : 50} minSize={20}>
              <PdfPane title="译文 PDF" pdfUrl={translatedPdfUrl} />
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
    </div>
  )
}
