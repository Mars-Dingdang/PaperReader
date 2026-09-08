import { useEffect, useRef, useState } from 'react'
import { Bot, BookOpen, UserRound, X } from 'lucide-react'
import {
  changePassword,
  makeDataUrl,
  updateProfile,
  updateProviderSettings,
  updateSettings,
  uploadAvatar,
  type AuthUser,
  type ProviderSettingsDraft,
  type UserSettings
} from '../lib/api'
import { ProviderSettingsForm } from './ProviderSettingsForm'

type Props = { open: boolean; user: AuthUser; onClose: () => void; onUserChange: (user: AuthUser) => void }
type Tab = 'account' | 'providers' | 'reading'

function providerDraft(settings: UserSettings): ProviderSettingsDraft {
  return {
    api_key: '', base_url: settings.base_url, model: settings.model,
    pdf_parser: settings.pdf_parser, mineru_api_key: '',
    mineru_base_url: settings.mineru_base_url,
    mineru_model_version: settings.mineru_model_version,
    mineru_language: settings.mineru_language,
    mineru_enable_formula: settings.mineru_enable_formula,
    mineru_enable_table: settings.mineru_enable_table,
    mineru_is_ocr: settings.mineru_is_ocr,
    vision_model: settings.vision_model
  }
}

export function ProfileModal({ open, user, onClose, onUserChange }: Props) {
  const [tab, setTab] = useState<Tab>('account')
  const [username, setUsername] = useState(user.username)
  const [settingsDraft, setSettingsDraft] = useState<UserSettings>(user.settings)
  const [providers, setProviders] = useState<ProviderSettingsDraft>(() => providerDraft(user.settings))
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    setTab(user.settings.api_key_configured ? 'account' : 'providers')
    setUsername(user.username)
    setSettingsDraft(user.settings)
    setProviders(providerDraft(user.settings))
    setCurrentPassword(''); setNewPassword(''); setConfirmPassword('')
    setMessage(null); setError(null)
    window.setTimeout(() => closeButtonRef.current?.focus(), 0)
  }, [open, user])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open, onClose])

  if (!open) return null

  async function saveCurrentTab() {
    setBusy(true); setError(null); setMessage(null)
    try {
      let nextUser = user
      if (tab === 'account' && username.trim() !== user.username) nextUser = await updateProfile(username.trim())
      if (tab === 'providers') {
        const next = await updateProviderSettings(providers)
        nextUser = { ...nextUser, settings: next }
        setProviders(providerDraft(next))
      }
      if (tab === 'reading') {
        const next = await updateSettings({ theme: settingsDraft.theme, vision_enabled: settingsDraft.vision_enabled, vision_mode: settingsDraft.vision_mode })
        nextUser = { ...nextUser, settings: next }
      }
      onUserChange(nextUser)
      setMessage('设置已安全保存。')
    } catch (e: any) { setError(e?.message || String(e)) } finally { setBusy(false) }
  }

  async function savePassword() {
    if (!currentPassword || !newPassword) return setError('请输入当前密码和新密码。')
    if (newPassword !== confirmPassword) return setError('两次输入的新密码不一致。')
    setBusy(true); setError(null); setMessage(null)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('')
      setMessage('密码已更新。')
    } catch (e: any) { setError(e?.message || String(e)) } finally { setBusy(false) }
  }

  async function changeAvatar(file?: File | null) {
    if (!file) return
    setBusy(true); setError(null)
    try { const next = await uploadAvatar(file); onUserChange(next); setMessage('头像已更新。') }
    catch (e: any) { setError(e?.message || String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal-card profile-card" role="dialog" aria-modal="true" aria-labelledby="profile-title" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div><div className="eyebrow">账户与偏好</div><div className="modal-title" id="profile-title">个人中心</div></div>
          <button ref={closeButtonRef} className="icon-btn" aria-label="关闭个人中心" onClick={onClose}><X size={17} /></button>
        </div>
        <div className="profile-layout">
          <nav className="profile-tabs" aria-label="个人中心导航">
            <button className={tab === 'account' ? 'active' : ''} onClick={() => setTab('account')}><UserRound size={16} />账号</button>
            <button className={tab === 'providers' ? 'active' : ''} onClick={() => setTab('providers')}><Bot size={16} />AI 服务{!user.settings.api_key_configured && <span className="attention-dot" />}</button>
            <button className={tab === 'reading' ? 'active' : ''} onClick={() => setTab('reading')}><BookOpen size={16} />阅读偏好</button>
          </nav>
          <div className="modal-body profile-body">
            {tab === 'account' && <>
              <div className="profile-hero">
                <label className="avatar-editor">
                  {user.avatar_url ? <img src={makeDataUrl(user.avatar_url)} alt={user.username} className="avatar-image large" /> : <div className="avatar-fallback large">{user.username.slice(0, 1).toUpperCase()}</div>}
                  <input type="file" accept=".png,.jpg,.jpeg,.webp" hidden onChange={(e) => void changeAvatar(e.target.files?.[0])} />
                  <span className="small">更换头像</span>
                </label>
                <div className="profile-meta"><div className="profile-name">{user.username}</div><div className="muted small">创建于 {new Date(user.created_at).toLocaleString()}</div><div className="muted small">最近登录：{user.last_login_at ? new Date(user.last_login_at).toLocaleString() : '首次登录'}</div></div>
              </div>
              <section className="profile-section"><h3>基本资料</h3><label className="field"><span>用户名</span><input value={username} onChange={(e) => setUsername(e.target.value)} /></label></section>
              <section className="profile-section"><h3>修改密码</h3><div className="field-grid three"><label className="field"><span>当前密码</span><input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} /></label><label className="field"><span>新密码</span><input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} /></label><label className="field"><span>确认新密码</span><input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} /></label></div><button className="btn align-start" disabled={busy} onClick={() => void savePassword()}>更新密码</button></section>
            </>}
            {tab === 'providers' && <ProviderSettingsForm value={providers} onChange={setProviders} apiKeyConfigured={user.settings.api_key_configured} mineruKeyConfigured={user.settings.mineru_api_key_configured} allowClear />}
            {tab === 'reading' && <section className="profile-section borderless"><div className="settings-section-heading"><div><h3>阅读体验</h3><p>这些偏好会跟随当前本地账号。</p></div></div><div className="field-grid two"><label className="field"><span>主题</span><select value={settingsDraft.theme} onChange={(e) => setSettingsDraft((v) => ({ ...v, theme: e.target.value as 'light' | 'dark' }))}><option value="light">浅色</option><option value="dark">深色</option></select></label><label className="field"><span>视觉校验</span><select value={settingsDraft.vision_enabled ? settingsDraft.vision_mode : 'off'} onChange={(e) => { const next = e.target.value; setSettingsDraft((v) => ({ ...v, vision_enabled: next !== 'off', vision_mode: next === 'manual' ? 'manual' : 'auto' })) }}><option value="auto">开启 · 自动</option><option value="manual">开启 · 人工</option><option value="off">关闭</option></select></label></div></section>}
            {(message || error) && <div className={error ? 'form-error' : 'form-success'} role="status">{error || message}</div>}
          </div>
        </div>
        <div className="modal-footer"><button className="btn" onClick={onClose} disabled={busy}>关闭</button><button className="btn primary" onClick={() => void saveCurrentTab()} disabled={busy}>{busy ? '保存中…' : '保存当前页'}</button></div>
      </div>
    </div>
  )
}
