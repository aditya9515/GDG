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
      <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(249,115,22,0.16),_transparent_40%),linear-gradient(180deg,#0d141c,#111827)] text-sm text-slate-300">
        Preparing the operations console...
      </div>
    )
  }

  return <>{children}</>
}
