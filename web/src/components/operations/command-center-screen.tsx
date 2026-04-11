'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { UrgencyBadge } from '@/components/cases/urgency-badge'
import { StatCard } from '@/components/dashboard/stat-card'
import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import {
  createIncident,
  createIngestionJob,
  extractIncident,
  getDashboardSummary,
  getDispatchOptions,
  listDispatches,
  listIngestionJobs,
  listIncidents,
  listResources,
  listTeams,
  scoreIncident,
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
  const [filter, setFilter] = useState<'ALL' | 'CRITICAL' | 'HIGH' | 'NEEDS_REVIEW'>('ALL')
  const [rawInput, setRawInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [importKind, setImportKind] = useState<'CSV' | 'PDF' | 'IMAGE'>('CSV')
  const [importTarget, setImportTarget] = useState<'incidents' | 'teams' | 'resources'>('incidents')
  const [importFile, setImportFile] = useState<File | null>(null)

  useEffect(() => {
    if (!user) {
      return
    }
    void refresh()
  }, [user])

  const filteredIncidents = useMemo(() => {
    if (filter === 'ALL') {
      return state.incidents
    }
    if (filter === 'NEEDS_REVIEW') {
      return state.incidents.filter((item) => item.status === 'NEEDS_REVIEW')
    }
    return state.incidents.filter((item) => item.urgency === filter)
  }, [filter, state.incidents])

  const markers = useMemo(
    () => [
      ...state.incidents.slice(0, 10).map((incident) => ({
        id: incident.case_id,
        label: incident.case_id,
        subtitle: `${incident.urgency} • ${incident.location_text || 'Location pending'}`,
        tone: 'incident' as const,
        point: incident.geo,
      })),
      ...state.teams.slice(0, 8).map((team) => ({
        id: team.team_id,
        label: team.display_name,
        subtitle: `${team.capability_tags.slice(0, 2).join(', ') || 'General response'}`,
        tone: 'team' as const,
        point: team.current_geo ?? team.base_geo,
      })),
      ...state.resources.slice(0, 8).map((resource) => ({
        id: resource.resource_id,
        label: resource.resource_type,
        subtitle: `${resource.quantity_available} available`,
        tone: 'resource' as const,
        point: resource.current_geo ?? resource.location,
      })),
    ],
    [state.incidents, state.resources, state.teams],
  )

  async function refresh() {
    if (!user) {
      return
    }
    const [summary, incidents, teams, resources, dispatches, jobs] = await Promise.all([
      getDashboardSummary(user),
      listIncidents(user),
      listTeams(user),
      listResources(user),
      listDispatches(user),
      listIngestionJobs(user),
    ])
    setState({ summary, incidents, teams, resources, dispatches, jobs })
  }

  async function submitManual() {
    if (!user || !rawInput.trim()) {
      return
    }
    setBusy(true)
    setMessage('Geo-anchoring incident and generating dispatch options...')
    try {
      const created = await createIncident(rawInput, user)
      await extractIncident(created.case_id, user)
      await scoreIncident(created.case_id, user)
      await getDispatchOptions(created.case_id, user)
      setRawInput('')
      setMessage(`Incident ${created.case_id} is ready for location review and dispatch.`)
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Failed to triage incident.')
    } finally {
      setBusy(false)
    }
  }

  async function submitImport() {
    if (!user || !importFile) {
      return
    }
    setBusy(true)
    setMessage(`Processing ${importFile.name}...`)
    try {
      await createIngestionJob(
        {
          kind: importKind,
          target: importTarget,
          file: importFile,
        },
        user,
      )
      setImportFile(null)
      setMessage(`${importFile.name} imported into ReliefOps.`)
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Import failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 border-b border-white/8 pb-5 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Maps-first command center</p>
          <h1 className="mt-2 text-3xl font-semibold">Locate, rank, and dispatch faster</h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">
            Turn scattered reports into geo-anchored incidents, match the nearest capable team and resources, and keep every move auditable.
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

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <StatCard label="Open Incidents" value={state.summary?.open_cases ?? '...'} />
        <StatCard label="Critical Queue" value={state.summary?.critical_cases ?? '...'} tone="alert" />
        <StatCard label="Mapped Incidents" value={state.summary?.mapped_cases ?? '...'} />
        <StatCard label="Mapped Teams" value={state.summary?.mapped_teams ?? '...'} />
        <StatCard label="Mapped Resources" value={state.summary?.mapped_resources ?? '...'} />
        <StatCard label="Active Dispatches" value={state.summary?.active_dispatches ?? '...'} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <TacticalMap title="Live operational surface" markers={markers} />

        <div className="space-y-6">
          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Manual intake</h2>
                <p className="mt-1 text-sm text-slate-400">Paste a field report and run the full triage pipeline.</p>
              </div>
              <button
                className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:border-white/20 hover:text-white"
                onClick={() => void refresh()}
              >
                Refresh
              </button>
            </div>
            <textarea
              className="mt-4 min-h-40 w-full rounded-[1.25rem] border border-white/10 bg-slate-950/70 px-4 py-4 text-sm text-stone-100 outline-none placeholder:text-slate-500"
              placeholder="Flood water rising fast near Shantinagar bridge. 4 people on rooftop incl 1 child. Need rescue boat ASAP."
              value={rawInput}
              onChange={(event) => setRawInput(event.target.value)}
            />
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                className="rounded-2xl bg-amber-300 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={busy || !rawInput.trim()}
                onClick={() => void submitManual()}
              >
                {busy ? 'Running...' : 'Create incident'}
              </button>
              <p className="text-sm text-slate-400">{message ?? 'Create incident -> extract -> score -> dispatch options.'}</p>
            </div>
          </div>

          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <h2 className="text-lg font-semibold">Quick imports</h2>
            <p className="mt-1 text-sm text-slate-400">Batch-import incidents, teams, or resources from CSV, or process PDF and image evidence.</p>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <select
                className="rounded-2xl border border-white/10 bg-slate-950/70 px-3 py-3 text-sm text-stone-100"
                value={importKind}
                onChange={(event) => setImportKind(event.target.value as 'CSV' | 'PDF' | 'IMAGE')}
              >
                <option value="CSV">CSV</option>
                <option value="PDF">PDF</option>
                <option value="IMAGE">IMAGE</option>
              </select>
              <select
                className="rounded-2xl border border-white/10 bg-slate-950/70 px-3 py-3 text-sm text-stone-100"
                value={importTarget}
                onChange={(event) => setImportTarget(event.target.value as 'incidents' | 'teams' | 'resources')}
              >
                <option value="incidents">Incidents</option>
                <option value="teams">Teams</option>
                <option value="resources">Resources</option>
              </select>
              <label className="flex cursor-pointer items-center justify-center rounded-2xl border border-dashed border-white/12 bg-white/3 px-3 py-3 text-sm text-slate-300">
                <input
                  className="hidden"
                  type="file"
                  accept={importKind === 'CSV' ? '.csv' : importKind === 'PDF' ? '.pdf' : 'image/*'}
                  onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
                />
                {importFile ? importFile.name : 'Choose file'}
              </label>
            </div>
            <div className="mt-4 flex items-center gap-3">
              <button
                className="rounded-2xl border border-white/10 px-4 py-3 text-sm font-semibold text-stone-100 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={busy || !importFile}
                onClick={() => void submitImport()}
              >
                Start import
              </button>
              <Link className="text-sm text-amber-100 transition hover:text-amber-50" href="/imports">
                Open import workspace
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Active dispatches</h2>
              <p className="mt-1 text-sm text-slate-400">Confirmed and in-progress operations.</p>
            </div>
            <Link className="text-sm text-amber-100 transition hover:text-amber-50" href="/dispatch">
              Full dispatch board
            </Link>
          </div>
          <div className="mt-4 grid gap-3">
            {state.dispatches.slice(0, 6).map((dispatch) => (
              <div key={dispatch.assignment_id} className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-semibold text-stone-100">{dispatch.assignment_id}</p>
                  <span className="rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                    {dispatch.status}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-400">
                  {dispatch.team_id ?? 'Unassigned team'} • ETA {dispatch.eta_minutes ?? 'Unknown'} min
                </p>
              </div>
            ))}
            {state.dispatches.length === 0 ? (
              <p className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4 text-sm text-slate-500">
                Dispatch confirmations will appear here once incidents are assigned.
              </p>
            ) : null}
          </div>
        </div>

        <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Ranked incident queue</h2>
              <p className="mt-1 text-sm text-slate-400">Urgency, map confidence, and duplicate risk in one queue.</p>
            </div>
            <span className="rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-500">
              {filteredIncidents.length} incidents
            </span>
          </div>
          <div className="mt-4 grid gap-3">
            {filteredIncidents.slice(0, 14).map((incident) => (
              <Link
                key={incident.case_id}
                href={`/incidents/${incident.case_id}`}
                className="rounded-[1.25rem] border border-white/8 bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.01))] p-4 transition hover:border-amber-300/25 hover:bg-white/6"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <UrgencyBadge urgency={incident.urgency} />
                      <span className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                        {incident.location_confidence}
                      </span>
                      {incident.duplicate_status !== 'NONE' ? (
                        <span className="rounded-full border border-rose-400/20 bg-rose-500/10 px-2.5 py-1 text-[11px] uppercase tracking-[0.18em] text-rose-200">
                          {incident.duplicate_status}
                        </span>
                      ) : null}
                    </div>
                    <h3 className="font-semibold text-stone-100">{incident.case_id}</h3>
                    <p className="line-clamp-2 text-sm leading-6 text-slate-400">{incident.raw_input}</p>
                  </div>
                  <div className="min-w-36 text-right">
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Priority</p>
                    <p className="mt-2 text-2xl font-semibold text-stone-100">{incident.priority_score ?? '--'}</p>
                    <p className="mt-1 text-xs text-slate-500">{incident.location_text || 'Location pending'}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Recent ingestion jobs</h2>
            <p className="mt-1 text-sm text-slate-400">Track what was imported, processed, and converted into operational records.</p>
          </div>
          <Link className="text-sm text-amber-100 transition hover:text-amber-50" href="/imports">
            View all imports
          </Link>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {state.jobs.slice(0, 6).map((job) => (
            <div key={job.job_id} className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold text-stone-100">{job.filename}</p>
                <span className="rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                  {job.status}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-400">
                {job.kind} {'->'} {job.target}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                {job.success_count} success • {job.warning_count} warnings
              </p>
            </div>
          ))}
          {state.jobs.length === 0 ? (
            <div className="rounded-[1.25rem] border border-white/8 bg-white/3 p-4 text-sm text-slate-500">
              Imports from CSV, PDF, and images will appear here once you start processing files.
            </div>
          ) : null}
        </div>
      </section>
    </div>
  )
}
