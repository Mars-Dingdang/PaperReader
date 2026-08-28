import { useState } from 'react'
import { login, register, type AuthUser } from '../lib/api'

type Props = {
  onAuthenticated: (user: AuthUser) => void
}

export function AuthScreen({ onAuthenticated }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    if (!username.trim() || !password) {
      setError('请输入账号和密码。')
      return
    }
    if (mode === 'register' && password !== confirmPassword) {
      setError('两次输入的密码不一致。')
      return
    }

    setBusy(true)
    setError(null)
    try {
      const user =
        mode === 'login'
          ? await login({
              username: username.trim(),
              password,
              remember_me: rememberMe
            })
          : await register({
              username: username.trim(),
              password
            })
      onAuthenticated(user)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-panel">
        <div className="auth-copy">
          <div className="brand auth-brand">
            <span className="brand-dot" />
            PaperReader
          </div>
          <h1>登录后继续你的论文工作流</h1>
          <p>
            每个账号会保留处理历史、收藏、视觉校验偏好和个人 LLM 配置。上传过的文档可以随时继续打开。
          </p>
          <div className="auth-highlights">
            <div className="auth-highlight">账号隔离的历史记录</div>
            <div className="auth-highlight">个人中心统一管理 API Key</div>
            <div className="auth-highlight">记住登录状态，换页不丢</div>
          </div>
        </div>

        <div className="auth-card">
          <div className="auth-tabs">
            <button
              className={`nav-item ${mode === 'login' ? 'active' : ''}`}
              onClick={() => {
                setMode('login')
                setError(null)
              }}
            >
              登录
            </button>
            <button
              className={`nav-item ${mode === 'register' ? 'active' : ''}`}
              onClick={() => {
                setMode('register')
                setError(null)
              }}
            >
              注册
            </button>
          </div>

          <div className="auth-form">
            <label className="field">
              <span>账号</span>
              <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="输入用户名" />
            </label>
            <label className="field">
              <span>密码</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="至少 6 位"
              />
            </label>
            {mode === 'register' && (
              <label className="field">
                <span>确认密码</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="再次输入密码"
                />
              </label>
            )}

            {mode === 'login' && (
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                />
                <span>记住我</span>
              </label>
            )}

            {error && <div className="form-error">{error}</div>}

            <button className="btn primary auth-submit" disabled={busy} onClick={() => void handleSubmit()}>
              {busy ? '处理中…' : mode === 'login' ? '登录' : '注册并进入'}
            </button>

            <div className="muted small">
              {mode === 'login'
                ? '没有账号？切换到注册即可创建本地账户。'
                : '注册后会自动登录，并建议先到个人中心填写 API Key。'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
