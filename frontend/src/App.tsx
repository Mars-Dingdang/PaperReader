import { lazy, Suspense, useEffect, useState } from 'react'
import { ApiError, getCurrentUser, getSetupStatus, type AuthUser, type SetupStatus } from './lib/api'
import { AuthScreen } from './components/AuthScreen'
import { SetupWizard } from './components/SetupWizard'

const ReaderPage = lazy(() => import('./pages/ReaderPage').then((module) => ({ default: module.ReaderPage })))

export function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [setup, setSetup] = useState<SetupStatus | null>(null)
  const [startupError, setStartupError] = useState<string | null>(null)

  async function initialize() {
    setLoading(true)
    setStartupError(null)
    try {
      const setupState = await getSetupStatus()
      setSetup(setupState)
      if (setupState.required) return
      try {
        const me = await getCurrentUser()
        setUser(me)
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) setUser(null)
        else throw error
      }
    } catch (error: any) {
      setStartupError(error?.message || '无法连接 PaperReader 服务。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void initialize()
    // initialize is intentionally run once at startup.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) {
    return (
      <div className="auth-shell">
        <div className="auth-card compact">
          <div className="muted">加载中…</div>
        </div>
      </div>
    )
  }

  if (startupError) return <div className="auth-shell"><div className="auth-card compact"><h2>服务暂时不可用</h2><p className="muted">{startupError}</p><button className="btn primary" onClick={() => void initialize()}>重新连接</button></div></div>

  if (setup?.required) return <SetupWizard status={setup} onComplete={() => void initialize()} />

  if (!user) {
    return <AuthScreen onAuthenticated={setUser} />
  }

  return <Suspense fallback={<div className="auth-shell"><div className="auth-card compact"><div className="muted">正在打开工作台…</div></div></div>}><ReaderPage user={user} onUserChange={setUser} onLogout={() => setUser(null)} /></Suspense>
}
