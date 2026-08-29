import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkBreaks from 'remark-breaks'
import rehypeKatex from 'rehype-katex'
import { BookOpen, PanelRightClose, Plus, Send, X } from 'lucide-react'
import type { ChatSession, ReferenceItem } from '../lib/api'
import { createChatSession, listChatSessions, sendChat } from '../lib/api'

type Props = {
  documentId?: string
  documentIds?: string[]
  scope?: 'document' | 'library'
  references: ReferenceItem[]
  onCollapse?: () => void
  title?: string
  greeting?: string
  className?: string
}

type Msg = { role: 'user' | 'assistant'; content: string; ts: number }

const TEMPLATE_PROMPTS = [
  { key: 'highlight', label: 'Highlight', prompt: 'Please summarize the paper highlights in 5-8 concise bullet points, with one sentence for each point.' },
  { key: 'baseline', label: 'Baseline', prompt: 'Please list the baseline methods compared in this paper and explain in a table-style format what differs from the proposed method.' },
  { key: 'limitations', label: 'Limitations', prompt: 'Please extract and summarize the paper limitations, including explicit limitations and potential hidden risks.' }
]

export function ChatPanel({
  documentId,
  documentIds,
  scope = 'document',
  references,
  onCollapse,
  title = 'Paper Chat',
  greeting,
  className = '',
}: Props) {
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState<Msg[]>([])
  const [loading, setLoading] = useState(false)
  const [showRefs, setShowRefs] = useState(false)
  const [selectedReference, setSelectedReference] = useState<ReferenceItem | null>(null)
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>()
  const [sessionsLoading, setSessionsLoading] = useState(false)

  const scrollRef = useRef<HTMLDivElement | null>(null)

  const selectedDocumentIds = useMemo(
    () => documentIds?.length ? documentIds : (documentId ? [documentId] : []),
    [documentId, documentIds]
  )

  useEffect(() => {
    let cancelled = false
    setSessionsLoading(true)
    setSelectedReference(null)
    void listChatSessions(scope, scope === 'document' ? documentId : undefined)
      .then((items) => {
        if (cancelled) return
        setSessions(items)
        const active = items[0]
        setActiveSessionId(active?.session_id)
        setHistory((active?.messages ?? []).map((m) => ({
          role: m.role,
          content: m.content,
          ts: Date.parse(m.created_at) || Date.now()
        })))
      })
      .catch((e) => console.error(e))
      .finally(() => { if (!cancelled) setSessionsLoading(false) })
    return () => { cancelled = true }
  }, [documentId, scope])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [history, loading])

  const refCountLabel = useMemo(() => `References · ${references.length}`, [references])

  function activateSession(sessionId: string) {
    const session = sessions.find((item) => item.session_id === sessionId)
    setActiveSessionId(sessionId || undefined)
    setHistory((session?.messages ?? []).map((m) => ({
      role: m.role,
      content: m.content,
      ts: Date.parse(m.created_at) || Date.now()
    })))
  }

  async function handleNewSession() {
    if (selectedDocumentIds.length === 0) return
    setSessionsLoading(true)
    try {
      const created = await createChatSession({
        scope,
        document_ids: selectedDocumentIds,
      })
      setSessions((items) => [created, ...items])
      setActiveSessionId(created.session_id)
      setHistory([])
    } catch (e: any) {
      alert(`新建会话失败：${e?.message ?? String(e)}`)
    } finally {
      setSessionsLoading(false)
    }
  }

  async function handleSend() {
    if (selectedDocumentIds.length === 0 || !message.trim() || loading) return
    const text = message.trim()
    let sessionId = activeSessionId
    setHistory((h) => [...h, { role: 'user', content: text, ts: Date.now() }])
    setMessage('')
    setLoading(true)
    try {
      if (!sessionId) {
        const created = await createChatSession({ scope, document_ids: selectedDocumentIds })
        sessionId = created.session_id
        setActiveSessionId(sessionId)
        setSessions((items) => [created, ...items])
      }
      const response = await sendChat({
        document_id: scope === 'document' ? documentId : undefined,
        document_ids: selectedDocumentIds,
        scope,
        session_id: sessionId,
        message: text,
      })
      setActiveSessionId(response.session_id)
      setHistory((h) => [...h, { role: 'assistant', content: response.answer, ts: Date.now() }])
      setSessions((items) => items.map((item) => item.session_id === response.session_id
        ? {
            ...item,
            title: item.title === '新会话' ? text.slice(0, 36) : item.title,
            updated_at: new Date().toISOString(),
            messages: [
              ...item.messages,
              { message_id: `local-user-${Date.now()}`, role: 'user', content: text, created_at: new Date().toISOString() },
              { message_id: `local-assistant-${Date.now()}`, role: 'assistant', content: response.answer, created_at: new Date().toISOString() },
            ]
          }
        : item
      ))
    } catch (e: any) {
      setHistory((h) => [
        ...h,
        { role: 'assistant', content: `**Error:** ${e?.message ?? String(e)}`, ts: Date.now() }
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={`chat ${className}`.trim()}>
      <div className="chat-header">
        <h3>{title}</h3>
        <div className="chat-actions">
          <select
            className="chat-session-select"
            aria-label="历史会话"
            value={activeSessionId ?? ''}
            disabled={sessionsLoading}
            onChange={(e) => activateSession(e.target.value)}
          >
            <option value="">历史会话</option>
            {sessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>{session.title}</option>
            ))}
          </select>
          <button
            className="icon-btn"
            title="新建会话"
            disabled={selectedDocumentIds.length === 0 || sessionsLoading}
            onClick={() => void handleNewSession()}
          >
            <Plus size={16} />
          </button>
          <button
            className={`icon-btn ${showRefs ? 'active' : ''}`}
            title={refCountLabel}
            onClick={() => setShowRefs((v) => !v)}
          >
            <BookOpen size={16} />
          </button>
          {onCollapse && (
            <button
              className="icon-btn chat-collapse-btn"
              aria-label="关闭 AI Chat"
              title="关闭 AI Chat"
              onClick={onCollapse}
            >
              <PanelRightClose size={17} />
            </button>
          )}
        </div>
      </div>

      <div className="template-row">
        {TEMPLATE_PROMPTS.map((item) => (
          <button key={item.key} className="template-chip" onClick={() => setMessage(item.prompt)}>
            {item.label}
          </button>
        ))}
      </div>

      <div className="chat-log" ref={scrollRef}>
        {history.length === 0 && (
          <div className="chat-empty muted">
            {selectedDocumentIds.length > 0
              ? (greeting || '选择上方模板或直接提问，开始与论文对话。')
              : '请先选择或上传文档。'}
          </div>
        )}
        {history.map((m, idx) => (
          <div key={idx} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>
              <div className="prose">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                >
                  {m.content}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        ))}
        {loading && (
          <div className="bubble-row assistant">
            <div className="bubble assistant typing">
              <span /><span /><span />
            </div>
          </div>
        )}
      </div>

      {showRefs && (
        <div className="ref-drawer">
          <div className="settings-head">
            <span>{refCountLabel}</span>
            <button className="icon-btn" onClick={() => setShowRefs(false)}><X size={14} /></button>
          </div>
          <div className="ref-drawer-body">
            <div className="ref-list">
              {references.length === 0 ? (
                <div className="muted small">未提取到参考文献</div>
              ) : (
                references.map((ref) => (
                  <button
                    key={ref.index}
                    className={`ref-item ${selectedReference?.index === ref.index ? 'active' : ''}`}
                    onClick={() => setSelectedReference(ref)}
                  >
                    [{ref.index}] {ref.text.slice(0, 100)}
                  </button>
                ))
              )}
            </div>
            <div className="ref-preview">
              {selectedReference ? (
                <>[{selectedReference.index}] {selectedReference.text}</>
              ) : (
                <span className="muted small">点击左侧条目查看详情</span>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="chat-input">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
          placeholder={selectedDocumentIds.length > 0 ? '向论文提问，例如：本文方法的核心创新是什么？' : '请先选择一个文档'}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              void handleSend()
            }
          }}
          disabled={selectedDocumentIds.length === 0}
        />
        <button
          className="send-btn"
          disabled={selectedDocumentIds.length === 0 || !message.trim() || loading}
          onClick={handleSend}
          title="发送 (⌘/Ctrl+Enter)"
        >
          <Send size={16} />
          {loading ? '思考中…' : '发送'}
        </button>
      </div>
    </div>
  )
}
