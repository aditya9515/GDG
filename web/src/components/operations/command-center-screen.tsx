'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { UrgencyBadge } from '@/components/cases/urgency-badge'
import { StatCard } from '@/components/dashboard/stat-card'
import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import {
  getDashboardSummary,
  listDispatches,
  listIngestionJobs,
  listIncidents,
  listResources,
  listTeams,
} from '@/lib/api'
import type { AssignmentDecision, CaseRecord, DashboardSummary, IngestionJob, ResourceInventory, Team } from '@/lib/types'

type LoadState = {
  summary: DashboardSummary | null
  incidents: CaseRecord[]
  teams: Team[]
  resources: ResourceInventory[]
  dispatches: AssignmentDecision[]
  jobs: IngestionJob[]
}

const filters = ['ALL', 'CRITICAL', 'HIGH', 'NEEDS_REVIEW'] as const

export function CommandCenterScreen() {
  const { user } = useAuth()
  const [state, setState] = useState<LoadState>({
    summary: null,
    incidents: [],
    teams: [],
    resources: [],
    dispatches: [],
    jobs: [],
  })
  const [filter, setFilter] = useState<(typeof filters)[number]>('ALL')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!user) {
      return
    }
    void refresh()
  }, [user, search])

  const filteredIncidents = useMemo(() => {
    const open = state.incidents.filter((item) => !['CLOSED', 'MERGED'].includes(item.status))
    if (filter === 'ALL') {
      return open
    }
    if (filter === 'NEEDS_REVIEW') {
      return open.filter((item) => item.status === 'NEEDS_REVIEW' || item.location_confidence === 'UNKNOWN')
    }
    return open.filter((item) => item.urgency === filter)
  }, [filter, state.incidents])

  const markers = useMemo(
    () => [
      ...state.incidents.map((incident) => ({
        id: incident.case_id,
        label: incident.case_id,
        subtitle: `${incident.urgency} | ${incident.location_text || 'Location pending'}`,
        tone: 'incident' as const,
        point: incident.geo,
      })),
      ...state.teams.map((team) => ({
        id: team.team_id,
        label: team.display_name,
        subtitle: `${team.capability_tags.slice(0, 2).join(', ') || 'General response'}`,
        tone: 'team' as const,
        point: team.current_geo ?? team.base_geo,
      })),
      ...state.resources.map((resource) => ({
        id: resource.resource_id,
        label: resource.resource_type,
        subtitle: `${resource.quantity_available} available`,
        tone: 'resource' as const,
        point: resource.current_geo ?? resource.location,
      })),
    ],
    [state.incidents, state.resources, state.teams],
  )

  const mapCoverage = useMemo(() => {
    const total =
      Math.max(state.incidents.length, 0) +
      Math.max(state.teams.length, 0) +
      Math.max(state.resources.length, 0)
    const mapped = markers.filter((item) => item.point).length
    return total > 0 ? Math.round((mapped / total) * 100) : 0
  }, [markers, state.incidents.length, state.resources.length, state.teams.length])

  const opsSignals = useMemo(() => {
    const open = state.incidents.filter((item) => !['CLOSED', 'MERGED'].includes(item.status))
    const critical = open.filter((item) => item.urgency === 'CRITICAL').length
    const needsReview = open.filter((item) => item.status === 'NEEDS_REVIEW' || item.location_confidence === 'UNKNOWN').length
    const duplicateRisk = open.filter((item) => item.duplicate_status !== 'NONE').length
    const unmapped = open.filter((item) => !item.geo).length
    const availableResources = state.resources.filter((item) => item.quantity_available > 0).length
    const activeDispatches = state.dispatches.filter((item) => ['CONFIRMED', 'IN_PROGRESS'].includes(item.status)).length
    const reviewPenalty = open.length > 0 ? Math.round((needsReview / open.length) * 35) : 0
    const duplicatePenalty = open.length > 0 ? Math.round((duplicateRisk / open.length) * 15) : 0
    const resourceScore = state.resources.length > 0 ? Math.round((availableResources / state.resources.length) * 20) : 12
    const readiness = Math.max(0, Math.min(100, Math.round(mapCoverage * 0.45 + resourceScore + 35 - reviewPenalty - duplicatePenalty)))

    return {
      open: open.length,
      critical,
      needsReview,
      duplicateRisk,
      unmapped,
      activeDispatches,
      availableResources,
      readiness,
      dispatchPressure: open.length > 0 ? Math.min(100, Math.round(((critical * 1.7 + activeDispatches) / open.length) * 100)) : 0,
    }
  }, [mapCoverage, state.dispatches, state.incidents, state.resources])

  async function refresh() {
    if (!user) {
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      const [summary, incidents, teams, resources, dispatches, jobs] = await Promise.all([
        getDashboardSummary(user),
        listIncidents(user, search),
        listTeams(user, search),
        listResources(user, search),
        listDispatches(user, search),
        listIngestionJobs(user, search),
      ])
      setState({ summary, incidents, teams, resources, dispatches, jobs })
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not refresh command center.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <header className="motion-rise flex flex-col gap-5 border border-white/14 bg-black/35 p-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-slate-400">
            <span className="h-1.5 w-1.5 rounded-full bg-white shadow-[0_0_18px_rgba(255,255,255,0.7)]" />
            Live command surface
          </div>
          <h1 className="mt-4 text-balance text-4xl font-semibold tracking-[-0.04em] text-white md:text-5xl">
            Relief allocation, mapped cleanly.
          </h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
            A focused operations board for incidents, teams, assets, routes, and dispatch state. Intake and imports live in their own workflow so this page stays calm under pressure.
          </p>
          {message ? <p className="mt-3 text-sm text-rose-200">{message}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Search map, queue, imports..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {filters.map((item) => (
            <button
              key={item}
              className={`rounded-full px-4 py-2 text-xs font-semibold tracking-[0.16em] transition ${
                filter === item
                  ? 'bg-white !text-black shadow-[0_12px_28px_rgba(255,255,255,0.1)]'
                  : 'border border-white/10 bg-white/[0.03] text-slate-400 hover:border-white/20 hover:text-white'
              }`}
              onClick={() => setFilter(item)}
            >
              {item}
            </button>
          ))}
          <button
            className="rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-semibold tracking-[0.16em] text-slate-300 transition hover:border-white/25 hover:text-white disabled:opacity-50"
            disabled={loading}
            onClick={() => void refresh()}
          >
            {loading ? 'SYNCING' : 'REFRESH'}
          </button>
          {user?.is_host ? (
            <Link
              className="rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-semibold tracking-[0.16em] text-slate-300 transition hover:border-white/25 hover:text-white"
              href="/organization#danger-zone"
            >
              RESET DATA
            </Link>
          ) : null}
        </div>
      </header>

      <section>
        <div className="motion-rise motion-delay-1">
          <TacticalMap
            title="Operational map"
            markers={markers}
            emptyMessage="Add a case with coordinates, or import teams/resources with map locations, to preview every operational point here."
          />
        </div>
      </section>

      <section className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
        <StatCard label="Open Incidents" value={state.summary?.open_cases ?? '...'} />
        <StatCard label="Critical" value={state.summary?.critical_cases ?? '...'} tone="alert" />
        <StatCard label="Mapped Incidents" value={state.summary?.mapped_cases ?? '...'} />
        <StatCard label="Teams" value={state.summary?.mapped_teams ?? '...'} />
        <StatCard label="Resources" value={state.summary?.mapped_resources ?? '...'} />
        <StatCard label="Active Dispatches" value={state.summary?.active_dispatches ?? '...'} />
      </section>

      <section className="grid gap-2 xl:grid-cols-[0.95fr_1.05fr]">
        <div className="surface-card motion-rise motion-delay-1 overflow-hidden p-5">
          <div className="absolute right-6 top-6 h-28 w-28 rounded-full border border-white/10">
              <span className="orbit-glow absolute left-1/2 top-1/2 h-2 w-2 rounded-full bg-white shadow-[0_0_22px_rgba(255,255,255,0.8)]" />
          </div>
          <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Operational readiness</p>
              <p className="mt-2 max-w-xl text-sm leading-6 text-slate-400">
                Blends map coverage, review debt, duplicate risk, dispatch load, and available stock into one judge-friendly signal.
              </p>
            </div>
            <ReadinessDial value={opsSignals.readiness} />
          </div>
          <div className="relative mt-6 grid gap-3 md:grid-cols-4">
            <SignalCard label="Location debt" value={opsSignals.unmapped} detail="incidents unmapped" tone={opsSignals.unmapped > 0 ? 'warn' : 'good'} />
            <SignalCard label="Review queue" value={opsSignals.needsReview} detail="needs operator check" tone={opsSignals.needsReview > 0 ? 'warn' : 'good'} />
            <SignalCard label="Duplicate risk" value={opsSignals.duplicateRisk} detail="possible merges" tone={opsSignals.duplicateRisk > 0 ? 'warn' : 'good'} />
            <SignalCard label="Stock online" value={opsSignals.availableResources} detail="available assets" tone="info" />
          </div>
        </div>

        <div className="surface-card motion-rise motion-delay-2 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Workflow state</p>
              <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-white">From evidence to dispatch</h2>
            </div>
            <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
              {opsSignals.dispatchPressure}% pressure
            </span>
          </div>
          <div className="mask-fade mt-6 grid grid-cols-4 gap-2">
            <PipelineStep label="Import" active={state.jobs.length > 0} />
            <PipelineStep label="Triage" active={opsSignals.open > 0} />
            <PipelineStep label="Assign" active={opsSignals.activeDispatches > 0} />
            <PipelineStep label="Resolve" active={state.dispatches.some((item) => item.status === 'COMPLETED')} />
          </div>
          <div className="mt-5 rounded-2xl border border-white/[0.07] bg-black/20 p-4">
            <p className="text-sm leading-6 text-slate-400">
              {opsSignals.critical > 0
                ? `${opsSignals.critical} critical incident${opsSignals.critical === 1 ? '' : 's'} should stay at the top of dispatch review.`
                : 'No critical incident is currently active. Keep improving map confidence and duplicate hygiene.'}
            </p>
          </div>
        </div>
      </section>

      <section className="grid gap-2 xl:grid-cols-[1fr_0.85fr]">
        <div className="motion-rise motion-delay-2 grid gap-4">
          <div className="surface-card p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Priority queue</p>
                <h2 className="mt-2 text-xl font-semibold tracking-[-0.02em] text-white">{filteredIncidents.length} active items</h2>
              </div>
              <Link className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-300 transition hover:border-white/25 hover:text-white" href="/imports">
                Open imports
              </Link>
            </div>
            <div className="mt-4 grid gap-2">
              {filteredIncidents.slice(0, 7).map((incident) => (
                <Link
                  key={incident.case_id}
                  href={`/incidents/${incident.case_id}`}
                  className="group rounded-2xl border border-white/[0.07] bg-white/[0.025] p-3 transition duration-300 hover:-translate-y-0.5 hover:border-white/15 hover:bg-white/[0.045]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <UrgencyBadge urgency={incident.urgency} />
                        <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                          {incident.location_confidence}
                        </span>
                      </div>
                      <p className="mt-2 font-medium text-slate-100">{incident.case_id}</p>
                      <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-500 transition group-hover:text-slate-400">
                        {incident.raw_input}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-[10px] uppercase tracking-[0.18em] text-slate-600">Score</p>
                      <p className="mt-1 text-2xl font-semibold text-white">{incident.priority_score ?? '--'}</p>
                    </div>
                  </div>
                </Link>
              ))}
              {filteredIncidents.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-white/10 p-5 text-sm text-slate-500">
                  No incidents match this filter.
                </div>
              ) : null}
            </div>
          </div>

          <div className="surface-card p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Map coverage</p>
            <div className="mt-4 flex items-end justify-between">
              <p className="text-5xl font-semibold tracking-[-0.06em] text-white">{mapCoverage}%</p>
              <p className="max-w-44 text-right text-sm leading-5 text-slate-500">
                Location confidence improves dispatch quality and route ranking.
              </p>
            </div>
            <div className="mt-5 h-2 overflow-hidden rounded-full bg-white/[0.06]">
              <div
                className="h-full rounded-full bg-white transition-all duration-700"
                style={{ width: `${mapCoverage}%` }}
              />
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-2 xl:grid-cols-[0.95fr_1.05fr]">
        <div className="surface-card motion-rise motion-delay-3 p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Dispatches</p>
              <h2 className="mt-2 text-xl font-semibold text-white">Active operations</h2>
            </div>
            <Link className="text-sm text-slate-300 transition hover:text-white" href="/dispatch">
              View board
            </Link>
          </div>
          <div className="mt-4 grid gap-2">
            {state.dispatches.slice(0, 6).map((dispatch) => (
              <div key={dispatch.assignment_id} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-stone-100">{dispatch.assignment_id}</p>
                  <span className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                    {dispatch.status}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-500">
                  {dispatch.team_id ?? 'Unassigned team'} | ETA {dispatch.eta_minutes ?? 'Unknown'} min
                </p>
              </div>
            ))}
            {state.dispatches.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-white/10 p-4 text-sm text-slate-500">
                Dispatch confirmations will appear here once assignments are approved.
              </p>
            ) : null}
          </div>
        </div>

        <div className="surface-card motion-rise motion-delay-4 p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Imports</p>
              <h2 className="mt-2 text-xl font-semibold text-white">Recent processing</h2>
            </div>
            <Link className="text-sm text-slate-300 transition hover:text-white" href="/imports">
              Open imports
            </Link>
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            {state.jobs.slice(0, 6).map((job) => (
              <div key={job.job_id} className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="truncate font-medium text-stone-100">{job.filename}</p>
                  <span className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                    {job.status}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-500">
                  {job.kind} {'->'} {job.target}
                </p>
              </div>
            ))}
            {state.jobs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-white/10 p-4 text-sm text-slate-500">
                Import previews and committed jobs will appear here.
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  )
}

function ReadinessDial({ value }: { value: number }) {
  const safeValue = Math.max(0, Math.min(100, value))
  return (
    <div className="relative grid h-32 w-32 shrink-0 place-items-center rounded-full border border-white/10 bg-black/20">
      <div
        className="absolute inset-2 rounded-full"
        style={{
          background: `conic-gradient(#ffffff ${safeValue * 3.6}deg, rgba(255,255,255,0.08) 0deg)`,
        }}
      />
      <div className="absolute inset-5 rounded-full bg-[#070b12]" />
      <div className="relative text-center">
        <p className="text-3xl font-semibold tracking-[-0.06em] text-white">{safeValue}</p>
        <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Ready</p>
      </div>
    </div>
  )
}

function SignalCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: number
  detail: string
  tone: 'good' | 'warn' | 'info'
}) {
  const toneClass =
    tone === 'good'
      ? 'text-white'
      : tone === 'warn'
        ? 'text-zinc-300'
        : 'text-zinc-100'
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4 transition hover:-translate-y-0.5 hover:bg-white/[0.04]">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
        <span className={`signal-dot h-1.5 w-1.5 rounded-full ${toneClass} bg-current`} />
      </div>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.06em] text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-500">{detail}</p>
    </div>
  )
}

function PipelineStep({ label, active }: { label: string; active: boolean }) {
  return (
    <div className="relative">
      <div
        className={`h-2 rounded-full transition-all duration-700 ${
          active ? 'bg-white shadow-[0_0_24px_rgba(255,255,255,0.2)]' : 'bg-white/[0.08]'
        }`}
      />
      <p className={`mt-2 text-center text-[10px] uppercase tracking-[0.18em] ${active ? 'text-slate-200' : 'text-slate-600'}`}>
        {label}
      </p>
    </div>
  )
}
