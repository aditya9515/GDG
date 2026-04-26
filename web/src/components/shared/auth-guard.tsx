'use client'

import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { LoadingState } from '@/components/shared/loading-state'

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
      <LoadingState
        title="Preparing operations console"
        message="Checking your session, organization access, and latest workspace data."
      />
    )
  }

  return <>{children}</>
}
