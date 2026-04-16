'use client'

import { createContext, useContext, useEffect, useMemo, useState } from 'react'

import { getMeWithToken, type SessionState } from '@/lib/api'
import { ENABLE_DEMO_AUTH, ENABLE_FIREBASE_AUTH } from '@/lib/config'
import { getFirebaseAuth, listenToIdTokenChanges, signInWithGoogle, signOutFromFirebase } from '@/lib/firebase'

type AuthContextValue = {
  user: SessionState | null
  isLoading: boolean
  error: string | null
  loginDemo: () => void
  loginGoogle: () => Promise<void>
  setActiveOrg: (orgId: string) => void
  refreshSession: () => Promise<SessionState | null>
  logout: () => Promise<void>
}

const STORAGE_KEY = 'reliefops_demo_session'
const ORG_STORAGE_KEY = 'reliefops_active_org'
const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionState | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function hydrateFromFirebaseToken(token: string, fallback: { uid: string; email?: string | null }) {
    const profile = await getMeWithToken(token)
    if (!profile.enabled) {
      throw new Error('Your account is signed in, but access to ReliefOps is disabled.')
    }
    const savedOrg = window.localStorage.getItem(ORG_STORAGE_KEY)
    const activeOrgId =
      (savedOrg && profile.organizations.some((org) => org.org_id === savedOrg) ? savedOrg : null) ??
      profile.active_org_id ??
      profile.default_org_id ??
      profile.organizations[0]?.org_id ??
      null
    const nextUser: SessionState = {
      uid: profile.uid || fallback.uid,
      email: profile.email ?? fallback.email ?? null,
      role: profile.role,
      enabled: profile.enabled,
      team_scope: profile.team_scope,
      organizations: profile.organizations,
      memberships: profile.memberships,
      active_org_id: activeOrgId,
      default_org_id: profile.default_org_id,
      is_host: profile.memberships.some((item) => item.org_id === activeOrgId && item.role === 'HOST'),
      token,
      mode: 'firebase',
    }
    setUser(nextUser)
    setError(null)
    window.localStorage.removeItem(STORAGE_KEY)
    document.cookie = 'reliefops_mode=firebase; path=/'
    return nextUser
  }

  useEffect(() => {
    const savedDemo = window.localStorage.getItem(STORAGE_KEY)
    if (savedDemo && ENABLE_DEMO_AUTH) {
      setUser(JSON.parse(savedDemo) as SessionState)
    }

    if (!ENABLE_FIREBASE_AUTH) {
      setIsLoading(false)
      return
    }

    const unsubscribe = listenToIdTokenChanges(async (firebaseUser) => {
      if (!firebaseUser) {
        const demo = window.localStorage.getItem(STORAGE_KEY)
        if (!demo) {
          setUser(null)
        }
        setIsLoading(false)
        return
      }

      setIsLoading(true)
      try {
        const token = await firebaseUser.getIdToken(true)
        await hydrateFromFirebaseToken(token, {
          uid: firebaseUser.uid,
          email: firebaseUser.email,
        })
      } catch (nextError) {
        setUser(null)
        setError(nextError instanceof Error ? nextError.message : 'Firebase session validation failed.')
        await signOutFromFirebase()
      } finally {
        setIsLoading(false)
      }
    })

    return () => unsubscribe()
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      error,
      loginDemo: () => {
        if (!ENABLE_DEMO_AUTH) {
          return
        }
        const nextUser: SessionState = {
          uid: 'demo-coordinator',
          email: 'demo@reliefops.local',
          role: 'INCIDENT_COORDINATOR',
          enabled: true,
          team_scope: [],
          organizations: [
            {
              org_id: 'org-demo-relief',
              name: 'Demo Relief NGO',
              host_uid: 'demo-coordinator',
              host_email: 'demo@reliefops.local',
              status: 'ACTIVE',
              settings: {},
              created_at: new Date().toISOString(),
            },
          ],
          memberships: [
            {
              membership_id: 'org-demo-relief-demo-coordinator',
              org_id: 'org-demo-relief',
              uid: 'demo-coordinator',
              email: 'demo@reliefops.local',
              role: 'HOST',
              status: 'ACTIVE',
              invited_by: 'seed-loader',
              joined_at: new Date().toISOString(),
              disabled_at: null,
            },
          ],
          active_org_id: 'org-demo-relief',
          default_org_id: 'org-demo-relief',
          is_host: true,
          mode: 'demo',
        }
        setUser(nextUser)
        setError(null)
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextUser))
        document.cookie = 'reliefops_mode=demo; path=/'
      },
      setActiveOrg: (orgId: string) => {
        setUser((current) => {
          if (!current) {
            return current
          }
          const nextUser = {
            ...current,
            active_org_id: orgId,
            is_host: current.memberships?.some((item) => item.org_id === orgId && item.role === 'HOST') ?? false,
          }
          window.localStorage.setItem(ORG_STORAGE_KEY, orgId)
          if (current.mode === 'demo') {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextUser))
          }
          return nextUser
        })
      },
      refreshSession: async () => {
        const auth = getFirebaseAuth()
        const firebaseUser = auth?.currentUser
        if (!firebaseUser) {
          return user
        }
        const token = await firebaseUser.getIdToken(true)
        return hydrateFromFirebaseToken(token, {
          uid: firebaseUser.uid,
          email: firebaseUser.email,
        })
      },
      loginGoogle: async () => {
        const credential = await signInWithGoogle()
        const token = await credential.user.getIdToken(true)
        setIsLoading(true)
        try {
          await hydrateFromFirebaseToken(token, {
            uid: credential.user.uid,
            email: credential.user.email,
          })
        } catch (nextError) {
          await signOutFromFirebase()
          throw nextError
        } finally {
          setIsLoading(false)
        }
      },
      logout: async () => {
        setUser(null)
        setError(null)
        window.localStorage.removeItem(STORAGE_KEY)
        window.localStorage.removeItem(ORG_STORAGE_KEY)
        document.cookie = 'reliefops_mode=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/'
        await signOutFromFirebase()
      },
    }),
    [error, isLoading, user],
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
