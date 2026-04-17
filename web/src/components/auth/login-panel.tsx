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
    <section className="mx-auto flex min-h-screen max-w-6xl items-center justify-center px-5 py-12">
      <div className="surface-card motion-rise grid w-full gap-8 p-6 md:p-8 xl:grid-cols-[1.18fr_0.82fr]">
        <div className="space-y-7">
          <div className="inline-flex w-fit items-center rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] text-slate-400">
            ReliefOps AI
          </div>
          <div className="space-y-3">
            <h1 className="max-w-2xl text-5xl font-semibold tracking-[-0.06em] text-white md:text-7xl">
              Minimal disaster ops. Maximum clarity.
            </h1>
            <p className="max-w-2xl text-sm leading-7 text-slate-400 md:text-base">
              Designed for disaster relief coordinators and medical desks. Intake, extraction, location resolution,
              duplicate warnings, route-aware recommendations, and dispatch timelines all flow through one operator console.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['Maps-first', 'Locate incidents, teams, and resources before dispatch.'],
              ['Preview-first', 'Import data, review drafts, then commit safely.'],
              ['Auditable', 'Every assignment keeps rationale, ETA, and operator history.'],
            ].map(([title, body]) => (
              <div key={title} className="rounded-2xl border border-white/8 bg-white/[0.025] p-4 transition hover:-translate-y-0.5 hover:bg-white/[0.04]">
                <h2 className="text-sm font-semibold text-white">{title}</h2>
                <p className="mt-2 text-sm leading-6 text-slate-500">{body}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-[1.5rem] border border-white/8 bg-black/24 p-6">
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-white">Enter console</h2>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Production uses Firebase Google sign-in and backend Firebase token verification. Local development can
            fall back to a seeded demo session.
          </p>
          <div className="mt-6 grid gap-3">
            <button
              className="rounded-2xl bg-white px-4 py-3 text-sm font-semibold text-slate-950 transition hover:-translate-y-0.5 hover:bg-slate-100 disabled:cursor-not-allowed disabled:bg-stone-400"
              disabled={!ENABLE_FIREBASE_AUTH || pendingMode !== null}
              onClick={enterGoogle}
            >
              {pendingMode === 'google' ? 'Signing in...' : 'Continue with Google'}
            </button>
            {ENABLE_DEMO_AUTH ? (
              <button
                className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-semibold text-slate-200 transition hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
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
