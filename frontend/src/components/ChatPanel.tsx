import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkBreaks from 'remark-breaks'
import rehypeKatex from 'rehype-katex'
import { BookOpen, Send, Settings2, X } from 'lucide-react'
import type { ReferenceItem } from '../lib/api'

type Props = {
  documentId?: string
  references: ReferenceItem[]
  onSend: (payload: {
    message: string
    override_api_key?: string
    override_base_url?: string
    override_model?: string
  }) => Promise<string>
}

type Msg = { role: 'user' | 'assistant'; content: string; ts: number }

const TEMPLATE_PROMPTS = [
  { key: 'highlight', label: 'Highlight', prompt: 'Please summarize the paper highlights in 5-8 concise bullet points, with one sentence for each point.' },
  { key: 'baseline', label: 'Baseline', prompt: 'Please list the baseline methods compared in this paper and explain in a table-style format what differs from the proposed method.' },
  { key: 'limitations', label: 'Limitations', prompt: 'Please extract and summarize the paper limitations, including explicit limitations and potential hidden risks.' }
]

const LS_KEY = 'paperreader.chat.settings'

export function ChatPanel({ documentId, references, onSend }: Props) {
  const [message, setMessage] = useState('')
  const [history, setHistory] = useState<Msg[]>([])
  const [loading, setLoading] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showRefs, setShowRefs] = useState(false)
  const [selectedReference, setSelectedReference] = useState<ReferenceItem | null>(null)

  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')

  const scrollRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LS_KEY)
      if (raw) {
        const obj = JSON.parse(raw)
        setApiKey(obj.apiKey ?? '')
        setBaseUrl(obj.baseUrl ?? '')
        setModel(obj.model ?? '')
      }
    } catch {}
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ apiKey, baseUrl, model }))
    } catch {}
  }, [apiKey, baseUrl, model])

  useEffect(() => {
    setHistory([])
    setSelectedReference(null)
  }, [documentId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [history, loading])

  const refCountLabel = useMemo(() => `References · ${references.length}`, [references])

  async function handleSend() {
    if (!documentId || !message.trim() || loading) return
    const text = message.trim()
    setHistory((h) => [...h, { role: 'user', content: text, ts: Date.now() }])
    setMessage('')
    setLoading(true)
    try {
      const answer = await onSend({
        message: text,
        override_api_key: apiKey || undefined,
        override_base_url: baseUrl || undefined,
        override_model: model || undefined
      })
      setHistory((h) => [...h, { role: 'assistant', content: answer, ts: Date.now() }])
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
    <div className="chat">
      <div className="chat-header">
        <h3>Paper Chat</h3>
        <div className="chat-actions">
          <button
            className={`icon-btn ${showRefs ? 'active' : ''}`}
            title={refCountLabel}
            onClick={() => setShowRefs((v) => !v)}
          >
            <BookOpen size={16} />
          </button>
          <button
            className={`icon-btn ${showSettings ? 'active' : ''}`}
            title="设置"
            onClick={() => setShowSettings((v) => !v)}
          >
            <Settings2 size={16} />
          </button>
        </div>
      </div>

      {showSettings && (
        <div className="chat-settings">
          <div className="settings-head">
            <span>对话设置（覆盖默认 LLM 配置）</span>
            <button className="icon-btn" onClick={() => setShowSettings(false)}><X size={14} /></button>
          </div>
          <label className="field">
            <span>API Key</span>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." />
          </label>
          <label className="field">
            <span>Base URL</span>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
          </label>
          <label className="field">
            <span>Model</span>
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="gpt-4o-mini" />
          </label>
          <div className="muted small">设置自动保存在浏览器本地</div>
        </div>
      )}

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
            {documentId ? '选择上方模板或直接提问，开始与论文对话。' : '请先在左侧选择或上传文档。'}
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
          placeholder={documentId ? '向论文提问，例如：本文方法的核心创新是什么？' : '请先选择一个文档'}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              void handleSend()
            }
          }}
          disabled={!documentId}
        />
        <button
          className="send-btn"
          disabled={!documentId || !message.trim() || loading}
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
