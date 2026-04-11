'use client'

import { createContext, useContext, useEffect, useMemo, useState } from 'react'

import { ENABLE_DEMO_AUTH } from '@/lib/config'
import { signInWithGoogle } from '@/lib/firebase'

type SessionUser = {
  uid: string
  email?: string | null
  role: string
  token?: string | null
  mode: 'demo' | 'firebase'
}

type AuthContextValue = {
  user: SessionUser | null
  isLoading: boolean
  loginDemo: () => void
  loginGoogle: () => Promise<void>
  logout: () => void
}

const STORAGE_KEY = 'reliefops_session'
const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved) {
      setUser(JSON.parse(saved) as SessionUser)
    }
    setIsLoading(false)
  }, [])

  const persist = (nextUser: SessionUser | null) => {
    setUser(nextUser)
    if (nextUser) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextUser))
      document.cookie = `reliefops_mode=${nextUser.mode}; path=/`
      return
    }
    window.localStorage.removeItem(STORAGE_KEY)
    document.cookie = 'reliefops_mode=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      loginDemo: () => {
        if (!ENABLE_DEMO_AUTH) {
          return
        }
        persist({
          uid: 'demo-coordinator',
          email: 'demo@reliefops.local',
          role: 'INCIDENT_COORDINATOR',
          mode: 'demo',
        })
      },
      loginGoogle: async () => {
        const credential = await signInWithGoogle()
        const token = await credential.user.getIdToken()
        persist({
          uid: credential.user.uid,
          email: credential.user.email,
          role: 'INCIDENT_COORDINATOR',
          token,
          mode: 'firebase',
        })
      },
      logout: () => persist(null),
    }),
    [isLoading, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
