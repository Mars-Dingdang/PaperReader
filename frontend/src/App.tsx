import { useEffect, useState } from 'react'
import { ReaderPage } from './pages/ReaderPage'
import { getCurrentUser, type AuthUser } from './lib/api'
import { AuthScreen } from './components/AuthScreen'

export function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      try {
        const me = await getCurrentUser()
        setUser(me)
      } catch {
        setUser(null)
      } finally {
        setLoading(false)
      }
    })()
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

  if (!user) {
    return <AuthScreen onAuthenticated={setUser} />
  }

  return <ReaderPage user={user} onUserChange={setUser} onLogout={() => setUser(null)} />
}
