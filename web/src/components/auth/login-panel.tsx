'use client'

import React from 'react'
import { useRouter } from 'next/navigation'
import { startTransition, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { InlineLoading } from '@/components/shared/loading-state'
import { ModeToggle } from '@/components/shared/mode-toggle'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ENABLE_DEMO_AUTH, ENABLE_FIREBASE_AUTH } from '@/lib/config'

export function LoginPanel() {
  const router = useRouter()
  const { error: authError, loginDemo, loginGoogle } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [pendingMode, setPendingMode] = useState<'demo' | 'google' | null>(null)

  const enterDemo = () => {
    setError(null)
    setPendingMode('demo')
    loginDemo()
    startTransition(() => router.push('/command-center'))
  }

  const enterGoogle = async () => {
    setError(null)
    setPendingMode('google')
    try {
      await loginGoogle()
      startTransition(() => router.push('/command-center'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google sign-in failed.')
      setPendingMode(null)
    }
  }

  return (
    <section className="mx-auto flex min-h-screen max-w-6xl items-center justify-center px-3 py-6 sm:px-6 sm:py-12">
      <div className="absolute end-4 top-4">
        <ModeToggle />
      </div>
      <Card className="motion-rise grid w-full overflow-hidden border-border/80 bg-card/90 shadow-2xl xl:grid-cols-[1.18fr_0.82fr]">
        <div className="space-y-5 sm:space-y-7">
          <CardHeader className="p-5 sm:p-8">
            <Badge variant="secondary" className="w-fit rounded-full px-3 py-1 uppercase tracking-[0.18em]">
              ReliefOps AI
            </Badge>
            <CardTitle className="mt-5 max-w-2xl text-4xl font-semibold tracking-[-0.06em] sm:text-5xl md:text-7xl">
              Minimal disaster ops. Maximum clarity.
            </CardTitle>
            <CardDescription className="max-w-2xl text-sm leading-7 md:text-base">
              Designed for disaster relief coordinators and medical desks. Intake, extraction, location resolution,
              duplicate warnings, route-aware recommendations, and dispatch timelines all flow through one operator console.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 px-5 pb-5 sm:px-8 sm:pb-8 md:grid-cols-3">
            {[
              ['Maps-first', 'Locate incidents, teams, and resources before dispatch.'],
              ['Preview-first', 'Import data, review drafts, then commit safely.'],
              ['Auditable', 'Every assignment keeps rationale, ETA, and operator history.'],
            ].map(([title, body]) => (
              <div key={title} className="rounded-2xl border border-border bg-background/55 p-4 transition hover:-translate-y-0.5 hover:bg-accent/60">
                <h2 className="text-sm font-semibold">{title}</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
              </div>
            ))}
          </CardContent>
        </div>
        <div className="border-t border-border bg-background/60 p-5 sm:p-8 xl:border-s xl:border-t-0">
          <h2 className="text-xl font-semibold tracking-[-0.03em]">Enter console</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Production uses Firebase Google sign-in and backend Firebase token verification. Local development can
            fall back to a seeded demo session.
          </p>
          <div className="mt-6 grid gap-3">
            <Button
              className="h-11 rounded-xl"
              disabled={!ENABLE_FIREBASE_AUTH || pendingMode !== null}
              onClick={enterGoogle}
            >
              {pendingMode === 'google' ? <InlineLoading label="Signing in" /> : 'Continue with Google'}
            </Button>
            {ENABLE_DEMO_AUTH ? (
              <Button
                variant="outline"
                className="h-11 rounded-xl"
                disabled={pendingMode !== null}
                onClick={enterDemo}
              >
                {pendingMode === 'demo' ? <InlineLoading label="Opening demo" /> : 'Use seeded demo access'}
              </Button>
            ) : null}
          </div>
          {!ENABLE_FIREBASE_AUTH ? (
            <p className="mt-4 text-xs leading-5 text-muted-foreground">
              Firebase env vars are missing, so Google sign-in is disabled until the hosting project is configured.
            </p>
          ) : null}
          {error || authError ? (
            <Alert variant="destructive" className="mt-4">
              <AlertDescription>{error ?? authError}</AlertDescription>
            </Alert>
          ) : null}
        </div>
      </Card>
    </section>
  )
}
