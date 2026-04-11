'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { StatCard } from '@/components/dashboard/stat-card'
import { UrgencyBadge } from '@/components/cases/urgency-badge'
import { useAuth } from '@/components/providers/auth-provider'
import { createCase, extractCase, getDashboardSummary, listCases, recommendCase, scoreCase } from '@/lib/api'
import type { CaseRecord, DashboardSummary } from '@/lib/types'

type LoadState = {
  summary: DashboardSummary | null
  cases: CaseRecord[]
}

export function InboxScreen() {
  const { user } = useAuth()
  const [state, setState] = useState<LoadState>({ summary: null, cases: [] })
  const [filter, setFilter] = useState<'ALL' | 'CRITICAL' | 'HIGH' | 'NEEDS_REVIEW'>('ALL')
  const [rawInput, setRawInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!user) {
      return
    }
    void refresh()
  }, [user])

  const filteredCases = useMemo(() => {
    if (filter === 'ALL') {
      return state.cases
    }
    if (filter === 'NEEDS_REVIEW') {
      return state.cases.filter((item) => item.status === 'NEEDS_REVIEW')
    }
    return state.cases.filter((item) => item.urgency === filter)
  }, [filter, state.cases])

  async function refresh() {
    if (!user) {
      return
    }
    const [summary, cases] = await Promise.all([getDashboardSummary(user), listCases(user)])
    setState({ summary, cases })
  }

  async function submitCase() {
    if (!rawInput.trim() || !user) {
      return
    }
    setBusy(true)
    setMessage('Creating case and running triage pipeline...')
    try {
      const created = await createCase(rawInput, user)
      await extractCase(created.case_id, user)
      await scoreCase(created.case_id, user)
      await recommendCase(created.case_id, user)
      setRawInput('')
      setMessage(`Case ${created.case_id} triaged and ready for review.`)
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to run triage pipeline.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 border-b border-white/8 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Operational inbox</p>
          <h1 className="mt-2 text-3xl font-semibold">Triage queue</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Intake new reports, rank urgent needs, inspect duplicate warnings, and move cases toward dispatch.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(['ALL', 'CRITICAL', 'HIGH', 'NEEDS_REVIEW'] as const).map((item) => (
            <button
              key={item}
              className={`rounded-full px-4 py-2 text-xs font-semibold tracking-[0.18em] ${
                filter === item ? 'bg-amber-300/12 text-amber-100' : 'bg-white/5 text-slate-300'
              }`}
              onClick={() => setFilter(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Open Cases" value={state.summary?.open_cases ?? '...'} />
        <StatCard label="Critical Queue" value={state.summary?.critical_cases ?? '...'} tone="alert" />
        <StatCard label="Assigned Today" value={state.summary?.assigned_today ?? '...'} />
        <StatCard label="Pending Duplicates" value={state.summary?.pending_duplicates ?? '...'} />
        <StatCard label="Avg. Confidence" value={state.summary?.average_confidence ?? '...'} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Live intake</h2>
              <p className="mt-1 text-sm text-slate-400">Paste a field report and run the text-first judge flow.</p>
            </div>
            <button
              className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:border-white/20 hover:text-white"
              onClick={() => void refresh()}
            >
              Refresh
            </button>
          </div>
          <textarea
            className="mt-4 min-h-44 w-full rounded-[1.25rem] border border-white/10 bg-slate-950/70 px-4 py-4 text-sm text-stone-100 outline-none ring-0 placeholder:text-slate-500"
            placeholder="Flood water rising fast near Shantinagar bridge. 4 people on rooftop incl 1 child. Need rescue boat ASAP."
            value={rawInput}
            onChange={(event) => setRawInput(event.target.value)}
          />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              className="rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={busy || !rawInput.trim()}
              onClick={() => void submitCase()}
            >
              {busy ? 'Running...' : 'Create + Triage'}
            </button>
            <p className="text-sm text-slate-400">{message ?? 'The pipeline runs create -> extract -> score -> recommend.'}</p>
          </div>
        </div>

        <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Ranked queue</h2>
              <p className="mt-1 text-sm text-slate-400">Highest urgency first with duplicate awareness and case status.</p>
            </div>
            <span className="rounded-full bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.16em] text-slate-400">
              {filteredCases.length} cases
            </span>
          </div>
          <div className="mt-4 grid gap-3">
            {filteredCases.slice(0, 16).map((item) => (
              <Link
                key={item.case_id}
                href={`/cases/${item.case_id}`}
                className="rounded-[1.25rem] border border-white/8 bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-4 transition hover:border-amber-300/25 hover:bg-white/6"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <UrgencyBadge urgency={item.urgency} />
                      <span className="rounded-full border border-white/8 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                        {item.status}
                      </span>
                      {item.duplicate_status !== 'NONE' ? (
                        <span className="rounded-full border border-rose-400/20 bg-rose-500/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-rose-200">
                          {item.duplicate_status}
                        </span>
                      ) : null}
                    </div>
                    <h3 className="font-semibold text-stone-100">{item.case_id}</h3>
                    <p className="line-clamp-2 text-sm leading-6 text-slate-400">{item.raw_input}</p>
                  </div>
                  <div className="min-w-32 text-right">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Priority score</p>
                    <p className="mt-2 text-2xl font-semibold text-stone-100">{item.priority_score ?? '--'}</p>
                    <p className="mt-1 text-xs text-slate-500">{item.location_text || 'Location pending'}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
