'use client'

import React from 'react'
import { useRouter } from 'next/navigation'
import { startTransition, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
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
    <section className="mx-auto flex min-h-screen max-w-5xl items-center justify-center px-6 py-12">
      <div className="grid w-full gap-6 rounded-[2rem] border border-white/10 bg-[rgba(14,20,28,0.88)] p-8 shadow-[0_24px_80px_rgba(0,0,0,0.35)] backdrop-blur xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-6">
          <div className="inline-flex w-fit items-center rounded-full border border-amber-400/30 bg-amber-400/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] text-amber-200">
            ReliefOps AI
          </div>
          <div className="space-y-3">
            <h1 className="max-w-2xl text-4xl font-semibold tracking-tight text-stone-100 md:text-5xl">
              Geo-anchor incidents and dispatch the nearest capable response.
            </h1>
            <p className="max-w-2xl text-sm leading-7 text-slate-300 md:text-base">
              Designed for disaster relief coordinators and medical desks. Intake, extraction, location resolution,
              duplicate warnings, route-aware recommendations, and dispatch timelines all flow through one operator console.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['Maps-First', 'Locate incidents, teams, and resources before dispatching the nearest capable unit.'],
              ['Technical Merit', 'Gemini extraction, deterministic scoring, and explainable route-aware matching.'],
              ['Judge Demo', 'Text or file intake to confirmed dispatch from one command center.'],
            ].map(([title, body]) => (
              <div key={title} className="rounded-2xl border border-white/8 bg-slate-950/40 p-4">
                <h2 className="text-sm font-semibold text-stone-100">{title}</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">{body}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/70 p-6">
          <h2 className="text-lg font-semibold text-stone-100">Enter the coordinator console</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Production uses Firebase Google sign-in and backend Firebase token verification. Local development can
            fall back to a seeded demo session.
          </p>
          <div className="mt-6 grid gap-3">
            <button
              className="rounded-2xl bg-stone-100 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-white disabled:cursor-not-allowed disabled:bg-stone-400"
              disabled={!ENABLE_FIREBASE_AUTH || pendingMode !== null}
              onClick={enterGoogle}
            >
              {pendingMode === 'google' ? 'Signing in...' : 'Continue with Google'}
            </button>
            {ENABLE_DEMO_AUTH ? (
              <button
                className="rounded-2xl border border-amber-300/30 bg-amber-300/10 px-4 py-3 text-sm font-semibold text-amber-100 transition hover:bg-amber-300/15 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={pendingMode !== null}
                onClick={enterDemo}
              >
                {pendingMode === 'demo' ? 'Opening demo...' : 'Use seeded demo access'}
              </button>
            ) : null}
          </div>
          {!ENABLE_FIREBASE_AUTH ? (
            <p className="mt-4 text-xs leading-5 text-slate-500">
              Firebase env vars are missing, so Google sign-in is disabled until the hosting project is configured.
            </p>
          ) : null}
          {error || authError ? <p className="mt-4 text-sm text-rose-300">{error ?? authError}</p> : null}
        </div>
      </div>
    </section>
  )
}
