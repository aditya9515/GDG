'use client'

import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useAuth } from '@/components/providers/auth-provider'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { isLoading, user } = useAuth()

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace('/login')
    }
    if (!isLoading && user && !user.active_org_id && pathname !== '/onboarding/create-organization') {
      router.replace('/onboarding/create-organization')
    }
  }, [isLoading, pathname, router, user])

  if (isLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-400">
        <div className="motion-rise rounded-2xl border border-white/10 bg-white/[0.03] px-5 py-4 shadow-[0_24px_80px_rgba(0,0,0,0.28)] backdrop-blur">
          Preparing the operations console...
        </div>
      </div>
    )
  }

  return <>{children}</>
}
