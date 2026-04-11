'use client'

import { useEffect, useState } from 'react'

import { StatCard } from '@/components/dashboard/stat-card'
import { useAuth } from '@/components/providers/auth-provider'
import { getDashboardSummary, getLatestEval } from '@/lib/api'
import type { DashboardSummary, EvalRunSummary } from '@/lib/types'

export default function AnalyticsPage() {
  const { user } = useAuth()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [latestEval, setLatestEval] = useState<EvalRunSummary | null>(null)

  useEffect(() => {
    if (!user) {
      return
    }
    void Promise.all([getDashboardSummary(user), getLatestEval(user)]).then(([nextSummary, evalRun]) => {
      setSummary(nextSummary)
      setLatestEval(evalRun)
    })
  }, [user])

  return (
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Analytics</p>
        <h1 className="mt-2 text-3xl font-semibold">Operational metrics and evaluation</h1>
      </header>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Backlog" value={summary?.open_cases ?? '...'} />
        <StatCard label="Critical Cases" value={summary?.critical_cases ?? '...'} tone="alert" />
        <StatCard label="Median Assign Time" value={summary?.median_time_to_assign_minutes ?? '...'} />
        <StatCard label="Confidence" value={summary?.average_confidence ?? '...'} />
      </section>
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Mapped Incidents" value={summary?.mapped_cases ?? '...'} />
        <StatCard label="Mapped Teams" value={summary?.mapped_teams ?? '...'} />
        <StatCard label="Mapped Resources" value={summary?.mapped_resources ?? '...'} />
        <StatCard label="Active Dispatches" value={summary?.active_dispatches ?? '...'} />
      </section>
      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <h2 className="text-lg font-semibold">Latest evaluation run</h2>
        {latestEval ? (
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <StatCard label="Extraction Accuracy" value={latestEval.extraction_accuracy} />
            <StatCard label="Critical Mislabels" value={latestEval.critical_mislabels} tone="alert" />
            <StatCard label="Duplicate Precision" value={latestEval.duplicate_precision} />
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-400">Run `npm run eval` after installing backend dependencies to populate this panel.</p>
        )}
      </section>
    </div>
  )
}
