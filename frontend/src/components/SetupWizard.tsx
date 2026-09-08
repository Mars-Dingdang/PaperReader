import { useMemo, useState } from 'react'
import { ShieldCheck, Sparkles } from 'lucide-react'
import { ProviderSettingsForm } from './ProviderSettingsForm'
import { saveInitialSetup, type ProviderSettingsDraft, type SetupStatus } from '../lib/api'

type Props = { status: SetupStatus; onComplete: () => void }

export function SetupWizard({ status, onComplete }: Props) {
  const initial = useMemo<ProviderSettingsDraft>(() => ({
    api_key: '',
    mineru_api_key: '',
    base_url: status.defaults?.base_url || 'https://api.openai.com/v1',
    model: status.defaults?.model || 'gpt-4o-mini',
    pdf_parser: status.defaults?.pdf_parser || 'local',
    mineru_base_url: status.defaults?.mineru_base_url || 'https://mineru.net/api/v4',
    mineru_model_version: status.defaults?.mineru_model_version || 'vlm',
    mineru_language: status.defaults?.mineru_language || 'en',
    mineru_enable_formula: status.defaults?.mineru_enable_formula ?? true,
    mineru_enable_table: status.defaults?.mineru_enable_table ?? true,
    mineru_is_ocr: status.defaults?.mineru_is_ocr ?? false,
    vision_model: status.defaults?.vision_model || 'GLM-4.5V'
  }), [status])
  const [draft, setDraft] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!draft.api_key.trim()) return setError('请输入大模型 API Key。')
    if (!draft.base_url.trim() || !draft.model.trim()) return setError('Base URL 和模型名称不能为空。')
    if (draft.pdf_parser === 'mineru' && !draft.mineru_api_key.trim()) return setError('使用 MinerU 时需要填写 MinerU API Key。')
    setBusy(true)
    setError(null)
    try {
      await saveInitialSetup(draft)
      onComplete()
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="setup-shell">
      <div className="setup-card">
        <header className="setup-header">
          <div className="setup-icon"><Sparkles size={24} /></div>
          <div><span className="eyebrow">首次启动</span><h1>连接你的 AI 服务</h1><p>完成一次配置后即可登录。不同账号的密钥会彼此隔离。</p></div>
        </header>
        <ProviderSettingsForm value={draft} onChange={setDraft} apiKeyConfigured={!!draft.api_key} mineruKeyConfigured={!!draft.mineru_api_key} />
        {error && <div className="form-error" role="alert">{error}</div>}
        <footer className="setup-footer">
          <div className="privacy-note"><ShieldCheck size={16} /><span>密钥先写入本机隐藏配置，登录后转存到加密数据库并从配置文件移除。</span></div>
          <button className="btn primary setup-submit" disabled={busy} onClick={() => void submit()}>{busy ? '正在保存…' : '保存并继续'}</button>
        </footer>
      </div>
    </div>
  )
}
