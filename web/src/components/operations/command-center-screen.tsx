'use client'

import Link from 'next/link'
import type React from 'react'
import { useEffect, useMemo, useState } from 'react'

import { UrgencyBadge } from '@/components/cases/urgency-badge'
import { StatCard } from '@/components/dashboard/stat-card'
import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { BusyOverlay, InlineLoading } from '@/components/shared/loading-state'
import { AboutButton, PageHeader } from '@/components/shared/mono-ui'
import {
  getDashboardSummary,
  listDispatches,
  listIngestionJobs,
  listIncidents,
  listResources,
  listTeams,
  listVolunteers,
} from '@/lib/api'
import { humanizeToken, incidentSummary } from '@/lib/format'
import type { AssignmentDecision, CaseRecord, DashboardSummary, IngestionJob, ResourceInventory, Team, Volunteer } from '@/lib/types'

type LoadState = {
  summary: DashboardSummary | null
  incidents: CaseRecord[]
  teams: Team[]
  volunteers: Volunteer[]
  resources: ResourceInventory[]
  dispatches: AssignmentDecision[]
  jobs: IngestionJob[]
}

const PRIORITY_PAGE_SIZE = 10

export function CommandCenterScreen() {
  const { user } = useAuth()
  const [state, setState] = useState<LoadState>({
    summary: null,
    incidents: [],
    teams: [],
    volunteers: [],
    resources: [],
    dispatches: [],
    jobs: [],
  })
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [priorityPage, setPriorityPage] = useState(1)

  useEffect(() => {
    if (!user) {
      return
    }
    void refresh()
  }, [user])

  const filteredIncidents = useMemo(() => {
    return state.incidents.filter((item) => !['CLOSED', 'MERGED'].includes(item.status))
  }, [state.incidents])

  const totalPriorityPages = Math.max(1, Math.ceil(filteredIncidents.length / PRIORITY_PAGE_SIZE))

  const paginatedIncidents = useMemo(() => {
    const start = (priorityPage - 1) * PRIORITY_PAGE_SIZE
    const end = start + PRIORITY_PAGE_SIZE
    return filteredIncidents.slice(start, end)
  }, [filteredIncidents, priorityPage])

  useEffect(() => {
    if (priorityPage > totalPriorityPages) {
      setPriorityPage(totalPriorityPages)
    }
  }, [priorityPage, totalPriorityPages])

  const markers = useMemo(
    () => [
      ...state.incidents.map((incident) => ({
        id: incident.case_id,
        label: incident.case_id,
        subtitle: `${humanizeToken(incident.urgency)} | ${incident.location_text || 'Location pending'}`,
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
        label: humanizeToken(resource.resource_type),
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
    const mappedOpen = open.filter((item) => item.geo).length
    const availableTeams = state.teams.filter((item) => ['AVAILABLE', 'ACTIVE', 'READY'].includes(String(item.availability_status ?? 'AVAILABLE'))).length
    const availableVolunteers = state.volunteers.filter((item) => ['AVAILABLE', 'ACTIVE', 'READY'].includes(String(item.availability_status ?? 'AVAILABLE'))).length
    const availableResources = state.resources.filter((item) => item.quantity_available > 0).length
    const activeDispatches = state.dispatches.filter((item) => ['CONFIRMED', 'IN_PROGRESS'].includes(item.status)).length
    const completedDispatches = state.dispatches.filter((item) => item.status === 'COMPLETED').length
    const hasOperationalData = state.incidents.length + state.teams.length + state.resources.length + state.volunteers.length > 0
    const dataQualityScore =
      open.length > 0 ? Math.max(0, Math.round(((open.length - needsReview - duplicateRisk * 0.5) / open.length) * 100)) : hasOperationalData ? 80 : 0
    const incidentMapScore = open.length > 0 ? Math.round((mappedOpen / open.length) * 100) : hasOperationalData ? mapCoverage : 0
    const teamScore = state.teams.length > 0 ? Math.round((availableTeams / state.teams.length) * 100) : 0
    const resourceScore = state.resources.length > 0 ? Math.round((availableResources / state.resources.length) * 100) : 0
    const dispatchCoverage = open.length > 0 ? Math.min(100, Math.round((activeDispatches / open.length) * 100)) : 0
    const readiness = Math.max(
      0,
      Math.min(
        100,
        Math.round(dataQualityScore * 0.32 + incidentMapScore * 0.24 + teamScore * 0.18 + resourceScore * 0.18 + dispatchCoverage * 0.08),
      ),
    )

    return {
      open: open.length,
      critical,
      needsReview,
      duplicateRisk,
      unmapped,
      activeDispatches,
      completedDispatches,
      availableTeams,
      availableVolunteers,
      availableResources,
      dataQualityScore,
      incidentMapScore,
      resourceScore,
      teamScore,
      dispatchCoverage,
      readiness,
      dispatchPressure: open.length > 0 ? Math.min(100, Math.round(((critical * 1.7 + activeDispatches) / open.length) * 100)) : 0,
      hasOperationalData,
    }
  }, [mapCoverage, state.dispatches, state.incidents, state.resources, state.teams, state.volunteers])

  async function refresh() {
    if (!user) {
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      const [summary, incidents, teams, volunteers, resources, dispatches, jobs] = await Promise.all([
        getDashboardSummary(user),
        listIncidents(user, ''),
        listTeams(user, ''),
        listVolunteers(user, ''),
        listResources(user, ''),
        listDispatches(user, ''),
        listIngestionJobs(user, ''),
      ])
      setState({ summary, incidents, teams, volunteers, resources, dispatches, jobs })
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not refresh command center.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative space-y-2">
      <BusyOverlay
        active={loading}
        title="Refreshing command center"
        message="Updating incidents, teams, volunteers, resources, dispatches, and processing history."
      />
      <PageHeader
        eyebrow="Live command surface"
        title={
          <span className="flex items-center gap-3">
            <span>Relief allocation, mapped cleanly.</span>
            {message ? (
              <span className="text-sm font-normal text-foreground">
                {message}
              </span>
            ) : null}
          </span>
        }
        description={
          <p>
            A focused operations board for incidents, teams, assets, routes, and dispatch state. Intake and imports live in their own workflow so this page stays calm under pressure.
          </p>
        }
        about="This dashboard combines current incidents, mapped field assets, available stock, dispatch activity, and recent processing history for the active organization. Use it to spot what needs review before planning or confirming response work."
      >
          <button
            className="rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-semibold tracking-[0.16em] text-slate-300 transition hover:border-white/25 hover:text-white disabled:opacity-50"
            disabled={loading}
            onClick={() => void refresh()}
          >
            {loading ? <InlineLoading label="SYNCING" /> : 'REFRESH'}
          </button>

          {user?.is_host ? (
            <Link
              className="rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-xs font-semibold tracking-[0.16em] text-slate-300 transition hover:border-white/25 hover:text-white"
              href="/organization#danger-zone"
            >
              RESET DATA
            </Link>
          ) : null}
      </PageHeader>

      <section>
        <div className="motion-rise motion-delay-1">
          <TacticalMap
            title="Operational map"
            markers={markers}
            emptyMessage="Add a case with coordinates, or import teams/resources with map locations, to preview every operational point here."
          />
        </div>
      </section>

      <section className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <StatCard label="Open Incidents" value={state.summary?.open_cases ?? '...'} />
        <StatCard label="Critical" value={state.summary?.critical_cases ?? '...'} tone="alert" />
        <StatCard label="Mapped Incidents" value={state.summary?.mapped_cases ?? '...'} />
        <StatCard label="Teams" value={state.summary?.mapped_teams ?? '...'} />
        <StatCard label="Resources" value={state.summary?.mapped_resources ?? '...'} />
        <StatCard label="Active Dispatches" value={state.summary?.active_dispatches ?? '...'} />
      </section>

      <section className="grid gap-2 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="surface-card motion-rise motion-delay-1 overflow-hidden p-5">
          <div className="absolute right-6 top-6 hidden h-28 w-28 rounded-full border border-white/10 sm:block">
            <span className="orbit-glow absolute left-1/2 top-1/2 h-2 w-2 rounded-full bg-white shadow-[0_0_22px_rgba(255,255,255,0.8)]" />
          </div>
          <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Operational readiness</p>
                <InfoTip label="Formula">
                  Readiness = 32% data quality + 24% incident map coverage + 18% available teams + 18% available resource stock + 8% dispatch coverage.
                  Data quality drops when open incidents need review, have unknown locations, or carry duplicate warnings.
                </InfoTip>
              </div>
              <p className="mt-2 max-w-xl text-sm leading-6 text-slate-400">
                A transparent health score for whether the current operation is ready to plan dispatches: clean incident data, mapped cases, available teams, usable stock, and active coverage.
              </p>
            </div>
            <ReadinessDial value={opsSignals.readiness} />
          </div>
          <div className="relative mt-6 grid gap-3 md:grid-cols-4">
            <SignalCard label="Data quality" value={`${opsSignals.dataQualityScore}%`} detail={`${opsSignals.needsReview} need review`} tone={opsSignals.needsReview > 0 ? 'warn' : 'good'} />
            <SignalCard label="Map coverage" value={`${opsSignals.incidentMapScore}%`} detail={`${opsSignals.unmapped} unmapped incidents`} tone={opsSignals.unmapped > 0 ? 'warn' : 'good'} />
            <SignalCard label="Available teams" value={opsSignals.availableTeams} detail={`${opsSignals.availableVolunteers} volunteers ready`} tone={opsSignals.availableTeams > 0 ? 'good' : 'warn'} />
            <SignalCard label="Usable stock" value={opsSignals.availableResources} detail={`${opsSignals.resourceScore}% resource availability`} tone={opsSignals.availableResources > 0 ? 'info' : 'warn'} />
          </div>
        </div>

        <div className="surface-card motion-rise motion-delay-2 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Workflow state</p>
                <InfoTip label="What this means">
                  This is a live snapshot, not a hidden workflow engine. Import turns on when any incidents, teams, volunteers, or resources exist. Triage uses open incidents. Assign uses active dispatches. Resolve uses completed dispatches.
                </InfoTip>
              </div>
              <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-white">From evidence to dispatch</h2>
            </div>
            <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-500">
              {opsSignals.dispatchPressure}% pressure
            </span>
          </div>
          <div className="minimal-scrollbar mt-6 grid grid-cols-4 gap-2 overflow-x-auto pb-1">
            <PipelineStep label="Import" active={opsSignals.hasOperationalData} description="At least one incident, team, volunteer, or resource exists." />
            <PipelineStep label="Triage" active={opsSignals.open > 0} description={`${opsSignals.open} open incidents are available for review.`} />
            <PipelineStep label="Assign" active={opsSignals.activeDispatches > 0} description={`${opsSignals.activeDispatches} dispatches are active.`} />
            <PipelineStep label="Resolve" active={opsSignals.completedDispatches > 0} description={`${opsSignals.completedDispatches} dispatches are completed.`} />
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

      <section className="motion-rise motion-delay-2">
        <div className="surface-card p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {Array.from({ length: totalPriorityPages }, (_, index) => {
                  const page = index + 1
                  const start = index * PRIORITY_PAGE_SIZE + 1
                  const end = Math.min((index + 1) * PRIORITY_PAGE_SIZE, filteredIncidents.length)

                  return (
                    <button
                      key={page}
                      onClick={() => setPriorityPage(page)}
                      className={`rounded-full px-3 py-1.5 text-xs font-semibold tracking-[0.16em] transition ${
                        priorityPage === page
                          ? 'light-surface shadow-[0_12px_28px_rgba(255,255,255,0.1)]'
                          : 'border border-white/10 bg-white/[0.03] text-slate-400 hover:border-white/20 hover:text-white'
                      }`}
                      title={`${start} to ${end}`}
                    >
                      {page}
                    </button>
                  )
                })}
              </div>

              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Priority queue</p>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-semibold tracking-[-0.02em] text-white">
                  {filteredIncidents.length} active items
                </h2>
                <AboutButton>
                  This queue shows open, non-merged cases ordered by the current incident list. Use it to jump into high-priority case details or send new evidence through Imports.
                </AboutButton>
              </div>
              <p className="mt-2 text-sm text-slate-500">
                Showing {filteredIncidents.length === 0 ? 0 : (priorityPage - 1) * PRIORITY_PAGE_SIZE + 1} to{' '}
                {Math.min(priorityPage * PRIORITY_PAGE_SIZE, filteredIncidents.length)} of {filteredIncidents.length}
              </p>
            </div>

            <Link
              className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-300 transition hover:border-white/25 hover:text-white"
              href="/imports"
            >
              Open imports
            </Link>
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-2">
            {paginatedIncidents.map((incident) => (
              <Link
                key={incident.case_id}
                href={`/incidents/${incident.case_id}`}
                className="group rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4 transition duration-300 hover:-translate-y-0.5 hover:border-white/15 hover:bg-white/[0.045]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <UrgencyBadge urgency={incident.urgency} />
                      <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                        {humanizeToken(incident.location_confidence)}
                      </span>
                    </div>
                    <p className="mt-2 font-medium text-slate-100">{incident.case_id}</p>
                    <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-500 transition group-hover:text-slate-400">
                      {incidentSummary(incident)}
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
                No active incidents available.
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <section className="motion-rise motion-delay-3">
        <div className="surface-card p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Map coverage</p>
                <AboutButton>
                  Map coverage counts incidents, teams, and resources that have usable coordinates. Better coverage improves routing, ETA checks, and operational visibility.
                </AboutButton>
              </div>
              <div className="mt-4 flex flex-wrap items-end gap-4">
                <p className="text-5xl font-semibold tracking-[-0.06em] text-white">{mapCoverage}%</p>
                <p className="max-w-xl text-sm leading-6 text-slate-500">
                  Location confidence improves dispatch quality, routing quality, and operational visibility across incidents, teams, and resources.
                </p>
              </div>
            </div>

            <div className="grid min-w-[240px] grid-cols-3 gap-3">
              <CoverageMiniCard label="Incidents" value={state.incidents.filter((item) => !!item.geo).length} total={state.incidents.length} />
              <CoverageMiniCard label="Teams" value={state.teams.filter((item) => !!(item.current_geo ?? item.base_geo)).length} total={state.teams.length} />
              <CoverageMiniCard label="Resources" value={state.resources.filter((item) => !!(item.current_geo ?? item.location)).length} total={state.resources.length} />
            </div>
          </div>

          <div className="mt-5 h-3 overflow-hidden rounded-full bg-white/[0.06]">
            <div
              className="h-full rounded-full bg-white transition-all duration-700"
              style={{ width: `${mapCoverage}%` }}
            />
          </div>
        </div>
      </section>

      <section className="grid gap-2 xl:grid-cols-[1fr_1fr]">
        <div className="surface-card motion-rise motion-delay-3 p-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Dispatches</p>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-semibold text-white">Active operations</h2>
                <AboutButton>
                  Active operations are recently confirmed dispatches. They show which assignments are already consuming team capacity or resource stock.
                </AboutButton>
              </div>
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
                    {humanizeToken(dispatch.status)}
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
              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Imports</p>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-semibold text-white">Recent processing</h2>
                <AboutButton>
                  Recent processing shows import jobs saved for the active organization, including previews, completed commits, warnings, and failed processing attempts.
                </AboutButton>
              </div>
              <p className="mt-2 max-w-lg text-sm leading-6 text-slate-500">
                Shows import and intake jobs saved for the active organization, including previews, completed commits, warnings, and failed processing attempts.
              </p>
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
                    {humanizeToken(job.status)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-500">
                  {humanizeToken(job.kind)} to {humanizeToken(job.target)}
                </p>
              </div>
            ))}
            {state.jobs.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-white/10 p-4 text-sm text-slate-500">
                No processing history was returned for the current organization yet.
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
        className="absolute inset-2 rounded-full dark:hidden"
        style={{
          background: `conic-gradient(#000000 ${safeValue * 3.6}deg, rgba(0,0,0,0.12) 0deg)`,
        }}
      />
      <div
        className="absolute inset-2 hidden rounded-full dark:block"
        style={{
          background: `conic-gradient(#ffffff ${safeValue * 3.6}deg, rgba(255,255,255,0.12) 0deg)`,
        }}
      />
      <div className="absolute inset-5 rounded-full bg-background" />
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
  value: number | string
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

function PipelineStep({ label, active, description }: { label: string; active: boolean; description: string }) {
  return (
    <div className="relative" title={description}>
      <div
        className={`h-2 rounded-full transition-all duration-700 ${
          active ? 'bg-white shadow-[0_0_24px_rgba(255,255,255,0.2)]' : 'bg-white/[0.08]'
        }`}
      />
      <p className={`mt-2 text-center text-[10px] uppercase tracking-[0.18em] ${active ? 'text-slate-200' : 'text-slate-600'}`}>
        {label}
      </p>
      <p className="mt-1 hidden text-center text-[10px] leading-4 text-slate-600 md:block">{active ? 'Active' : 'Waiting'}</p>
    </div>
  )
}

function InfoTip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 transition hover:border-white/25 hover:text-white"
      >
        {label}
      </button>
      <span className="pointer-events-none absolute left-0 top-full z-30 mt-2 w-[min(22rem,80vw)] rounded-2xl border border-white/12 bg-black/95 p-4 text-sm normal-case leading-6 tracking-normal text-slate-300 opacity-0 shadow-[0_24px_80px_rgba(0,0,0,0.45)] transition group-hover:opacity-100 group-focus-within:opacity-100">
        {children}
      </span>
    </span>
  )
}

function CoverageMiniCard({
  label,
  value,
  total,
}: {
  label: string
  value: number
  total: number
}) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
      <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-white">
        {value}
        <span className="ml-1 text-sm text-slate-500">/ {total}</span>
      </p>
    </div>
  )
}
