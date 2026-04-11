'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useAuth } from '@/components/providers/auth-provider'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { isLoading, user } = useAuth()

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace('/login')
    }
  }, [isLoading, router, user])

  if (isLoading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(249,115,22,0.16),_transparent_40%),linear-gradient(180deg,#0d141c,#111827)] text-sm text-slate-300">
        Preparing the operations console...
      </div>
    )
  }

  return <>{children}</>
}
