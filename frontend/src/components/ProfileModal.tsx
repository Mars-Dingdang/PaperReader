import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import {
  changePassword,
  makeDataUrl,
  updateProfile,
  updateSettings,
  uploadAvatar,
  type AuthUser,
  type UserSettings
} from '../lib/api'

type Props = {
  open: boolean
  user: AuthUser
  onClose: () => void
  onUserChange: (user: AuthUser) => void
}

export function ProfileModal({ open, user, onClose, onUserChange }: Props) {
  const [username, setUsername] = useState(user.username)
  const [settingsDraft, setSettingsDraft] = useState<UserSettings>(user.settings)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setUsername(user.username)
    setSettingsDraft(user.settings)
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setMessage(null)
    setError(null)
  }, [open, user])

  if (!open) return null

  async function handleProfileSave() {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      let nextUser = user
      if (username.trim() !== user.username) {
        nextUser = await updateProfile(username.trim())
      }
      const nextSettings = await updateSettings(settingsDraft)
      nextUser = { ...nextUser, settings: nextSettings }
      onUserChange(nextUser)
      setMessage('个人信息已保存。')
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  async function handlePasswordSave() {
    if (!currentPassword || !newPassword) {
      setError('请输入当前密码和新密码。')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致。')
      return
    }
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setMessage('密码已更新。')
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  async function handleAvatarChange(file?: File | null) {
    if (!file) return
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const nextUser = await uploadAvatar(file)
      onUserChange(nextUser)
      setMessage('头像已更新。')
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card profile-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title">个人中心</div>
          <button className="icon-btn" title="关闭" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="modal-body profile-body">
          <div className="profile-hero">
            <label className="avatar-editor">
              {user.avatar_url ? (
                <img src={makeDataUrl(user.avatar_url)} alt={user.username} className="avatar-image large" />
              ) : (
                <div className="avatar-fallback large">{user.username.slice(0, 1).toUpperCase()}</div>
              )}
              <input
                type="file"
                accept=".png,.jpg,.jpeg,.webp"
                style={{ display: 'none' }}
                onChange={(e) => void handleAvatarChange(e.target.files?.[0])}
              />
              <span className="small">点击更换头像</span>
            </label>
            <div className="profile-meta">
              <div className="profile-name">{user.username}</div>
              <div className="muted small">创建时间：{new Date(user.created_at).toLocaleString()}</div>
              <div className="muted small">
                最近登录：{user.last_login_at ? new Date(user.last_login_at).toLocaleString() : '首次登录'}
              </div>
            </div>
          </div>

          <div className="profile-grid">
            <section className="profile-section">
              <h3>基本资料</h3>
              <label className="field">
                <span>用户名</span>
                <input value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
            </section>

            <section className="profile-section">
              <h3>LLM 设置</h3>
              <label className="field">
                <span>API Key</span>
                <input
                  type="password"
                  value={settingsDraft.api_key}
                  onChange={(e) => setSettingsDraft((v) => ({ ...v, api_key: e.target.value }))}
                  placeholder="sk-..."
                />
              </label>
              <label className="field">
                <span>Base URL</span>
                <input
                  value={settingsDraft.base_url}
                  onChange={(e) => setSettingsDraft((v) => ({ ...v, base_url: e.target.value }))}
                  placeholder="https://api.openai.com/v1"
                />
              </label>
              <label className="field">
                <span>Model</span>
                <input
                  value={settingsDraft.model}
                  onChange={(e) => setSettingsDraft((v) => ({ ...v, model: e.target.value }))}
                  placeholder="gpt-4o-mini"
                />
              </label>
            </section>

            <section className="profile-section">
              <h3>阅读偏好</h3>
              <label className="field">
                <span>主题</span>
                <select
                  value={settingsDraft.theme}
                  onChange={(e) => setSettingsDraft((v) => ({ ...v, theme: e.target.value as 'light' | 'dark' }))}
                >
                  <option value="light">浅色</option>
                  <option value="dark">深色</option>
                </select>
              </label>
              <label className="field">
                <span>视觉校验</span>
                <select
                  value={settingsDraft.vision_enabled ? settingsDraft.vision_mode : 'off'}
                  onChange={(e) => {
                    const next = e.target.value
                    setSettingsDraft((v) => ({
                      ...v,
                      vision_enabled: next !== 'off',
                      vision_mode: next === 'manual' ? 'manual' : 'auto'
                    }))
                  }}
                >
                  <option value="auto">开启 · 自动</option>
                  <option value="manual">开启 · 人工</option>
                  <option value="off">关闭</option>
                </select>
              </label>
            </section>

            <section className="profile-section">
              <h3>修改密码</h3>
              <label className="field">
                <span>当前密码</span>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                />
              </label>
              <label className="field">
                <span>新密码</span>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </label>
              <label className="field">
                <span>确认新密码</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </label>
              <button className="btn" disabled={busy} onClick={() => void handlePasswordSave()}>
                更新密码
              </button>
            </section>
          </div>

          {(message || error) && (
            <div className={error ? 'form-error' : 'form-success'}>{error || message}</div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={onClose} disabled={busy}>关闭</button>
          <button className="btn primary" onClick={() => void handleProfileSave()} disabled={busy}>
            保存设置
          </button>
        </div>
      </div>
    </div>
  )
}
