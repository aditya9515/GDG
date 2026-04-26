'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { Graph2Panel } from '@/components/dispatch/graph2-panel'
import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { BusyOverlay, InlineLoading } from '@/components/shared/loading-state'
import { AboutButton, PageHeader } from '@/components/shared/mono-ui'
import { Button } from '@/components/ui/button'
import { useCaseManager } from '@/hooks/use-case-manager'
import { listIncidents } from '@/lib/api'
import { humanizeToken, incidentSummary } from '@/lib/format'
import type { CaseRecord } from '@/lib/types'

import { UrgencyBadge } from './urgency-badge'

const filters = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"] as const

type CaseFilter = (typeof filters)[number]

export function CasesScreen() {
  const ITEMS_PER_PAGE = 10
  const [page, setPage] = useState(1)
  const { user } = useAuth()
  const [incidents, setIncidents] = useState<CaseRecord[]>([])
  const [filter, setFilter] = useState<CaseFilter>('ALL')
  const [search, setSearch] = useState('')
  const [planningCaseId, setPlanningCaseId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [rawInput, setRawInput] = useState('')
  const [locationText, setLocationText] = useState('')
  const [lat, setLat] = useState('')
  const [lng, setLng] = useState('')

  const { createCaseFromInput, creatingCase, removeCase, removingCaseId } = useCaseManager({
    session: user,
    onMessage: setMessage,
    onRefresh: refresh,
    onDeleted: (caseId) => setIncidents((current) => current.filter((incident) => incident.case_id !== caseId)),
  })


  useEffect(() => {
    setPage(1)
  }, [filter, search])

  useEffect(() => {
    if (!user) {
      return
    }
    void refresh()
  }, [user, search])

  useEffect(() => {
    if (!planningCaseId) {
      return
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setPlanningCaseId(null)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [planningCaseId])

  const filteredIncidents = useMemo(() => {
    if (filter === 'ALL') {
      return incidents
    }
    return incidents.filter((incident) => incident.urgency === filter)
  }, [filter, incidents])

  const totalPages = Math.max(1, Math.ceil(filteredIncidents.length / ITEMS_PER_PAGE))

  const paginatedIncidents = useMemo(() => {
    const start = (page - 1) * ITEMS_PER_PAGE
    return filteredIncidents.slice(start, start + ITEMS_PER_PAGE)
  }, [filteredIncidents, page])

  const markers = useMemo(
    () =>
      filteredIncidents
        .filter((incident) => incident.geo)
        .map((incident) => ({
          id: incident.case_id,
          label: incident.case_id,
          subtitle: `${humanizeToken(incident.urgency)} | ${incident.location_text || 'Location pending'}`,
          tone: 'incident' as const,
          point: incident.geo,
        })),
    [filteredIncidents],
  )

  async function refresh() {
    if (!user) {
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      setIncidents(await listIncidents(user, search))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load cases.')
    } finally {
      setLoading(false)
    }
  }

  async function submitCase() {
    const created = await createCaseFromInput({ rawInput, locationText, lat, lng })
    if (created) {
      setRawInput('')
      setLocationText('')
      setLat('')
      setLng('')
    }
  }

  function closePlanningDialog() {
    setPlanningCaseId(null)
  }

  return (
    <div className="relative space-y-2">
      <BusyOverlay active={loading} title="Refreshing cases" message="Loading the latest incident registry for this organization." />
      <PageHeader
        eyebrow="Case registry"
        title="Cases"
        description={
          <>
            <p>Add, map, open, and remove incidents for the active organization. Bulk CSV, PDF, and image parsing stays in Imports.</p>
            {message ? <p className="mt-2 text-foreground">{message}</p> : null}
          </>
        }
        about="Cases are the incident records dispatch planning uses. Keep each case summary, urgency, duplicate state, and location clear so recommendations and maps stay trustworthy."
      >
        <Button variant="outline" disabled={loading} onClick={() => void refresh()}>
          {loading ? <InlineLoading label="Refreshing" /> : 'Refresh'}
        </Button>
      </PageHeader>

      <section className="grid gap-2 xl:grid-cols-2">
        <div className="surface-card motion-rise motion-delay-1 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Create case</p>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-semibold tracking-[-0.03em] text-white">Quick single incident</h2>
                <AboutButton>
                  Use quick create for one urgent incident or field report. Add coordinates when available so the case appears on the map and can be routed during dispatch planning.
                </AboutButton>
              </div>
            </div>
            <span className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-400">
              Manual
            </span>
          </div>
          <textarea
            className="mt-4 min-h-28 w-full resize-none rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm leading-5 text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Raw report, call note, or copied message. Example: Ambulance needed for pregnant woman in labour, road flooded near Ward 4."
            value={rawInput}
            onChange={(event) => setRawInput(event.target.value)}
          />
          <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)]">
            <input
              className="w-full min-w-0 rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder="Location label or address"
              value={locationText}
              onChange={(event) => setLocationText(event.target.value)}
            />
            <input
              className="w-full min-w-0 rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder="Latitude"
              value={lat}
              onChange={(event) => setLat(event.target.value)}
            />
            <input
              className="w-full min-w-0 rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder="Longitude"
              value={lng}
              onChange={(event) => setLng(event.target.value)}
            />
          </div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs leading-5 text-slate-500">Coordinates are optional; valid pins make the case visible on the map immediately.</p>
            <button
              className="rounded-xl border border-foreground bg-foreground px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-background transition hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={creatingCase || rawInput.trim().length < 3}
              onClick={() => void submitCase()}
            >
              {creatingCase ? 'Creating case...' : 'Create case'}
            </button>
          </div>
        </div>

        <div className="motion-rise motion-delay-2">
          <TacticalMap
            title="Case map preview"
            markers={markers}
            emptyMessage="No mapped cases yet. Create a case with coordinates or update locations from case detail."
          />
        </div>
      </section>

      <section className="surface-card motion-rise motion-delay-2 p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex items-center gap-2">
                <p className="text-xs uppercase tracking-[0.2em] text-slate-500">All cases</p>
              </div>
              <div className="flex items-center gap-1">
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((pageNumber) => (
                  <button
                    key={pageNumber}
                    className={`rounded-xl border px-2.5 py-1 text-[11px] font-semibold transition ${
                      page === pageNumber
                        ? 'border-foreground bg-foreground text-background'
                        : 'border-border text-muted-foreground hover:border-foreground/25 hover:bg-muted hover:text-foreground'
                    }`}
                    onClick={() => setPage(pageNumber)}
                  >
                    {pageNumber}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold tracking-[-0.03em] text-white">
                {filteredIncidents.length === 0
                  ? '0 visible'
                  : `${(page - 1) * ITEMS_PER_PAGE + 1}-${Math.min(page * ITEMS_PER_PAGE, filteredIncidents.length)} of ${filteredIncidents.length} visible`}
              </h2>
              <AboutButton>
                This list shows the current incident queue for the active organization. Filter by urgency, search reports, open a detail page, or launch focused dispatch from a case.
              </AboutButton>
            </div>
          </div>
          <div className="flex w-full flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:items-center lg:w-auto">
            <input
              className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25 sm:min-w-64 sm:w-auto"
              placeholder="Search cases..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {filters.map((item) => (
              <button
                key={item}
                className={`rounded-xl border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] transition ${
                  filter === item
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-border text-muted-foreground hover:border-foreground/25 hover:bg-muted hover:text-foreground'
                }`}
                onClick={() => setFilter(item)}
              >
                {humanizeToken(item)}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 grid gap-2">
          {paginatedIncidents.map((incident) => (
            <article key={incident.case_id} className="rounded-2xl border border-border bg-background/70 p-3 text-foreground transition hover:border-foreground/20 hover:bg-muted/60">
              <div className="grid gap-3 xl:grid-cols-[11rem_minmax(0,1fr)_14rem] xl:items-center">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <UrgencyBadge urgency={incident.urgency} />
                    <span className="rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      {humanizeToken(incident.status)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm font-semibold text-foreground">{incident.case_id}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground">Score {incident.priority_score ?? 'pending'}</p>
                </div>

                <div className="min-w-0">
                  <p className="line-clamp-2 text-sm leading-5 text-foreground">{incidentSummary(incident)}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                    <span className="rounded-xl border border-border px-2 py-1 uppercase tracking-[0.14em]">{humanizeToken(incident.location_confidence)}</span>
                    <span className="truncate rounded-xl border border-border px-2 py-1">{incident.location_text || 'No location yet'}</span>
                    <span className="rounded-xl border border-border px-2 py-1">{incident.geo ? `${incident.geo.lat.toFixed(4)}, ${incident.geo.lng.toFixed(4)}` : 'Unmapped'}</span>
                  </div>
                </div>

                <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap xl:justify-end">
                  <Link
                    className="rounded-xl border border-border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground"
                    href={`/cases/${incident.case_id}`}
                  >
                    Open
                  </Link>
                  <button
                    className="rounded-xl border border-border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground"
                    onClick={() => setPlanningCaseId(incident.case_id)}
                  >
                    Plan
                  </button>
                  <button
                    aria-label={`Remove ${incident.case_id}`}
                    className="rounded-xl border border-border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50"
                    disabled={removingCaseId === incident.case_id}
                    onClick={() => void removeCase(incident.case_id)}
                  >
                    {removingCaseId === incident.case_id ? 'Removing' : 'Remove'}
                  </button>
                </div>
              </div>
            </article>
          ))}
          {filteredIncidents.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/10 p-8 text-center text-sm text-slate-500">
              {incidents.length === 0 ? 'No cases exist in this organization yet.' : 'No cases match this filter.'}
            </div>
          ) : null}
        </div>
      </section>

      {planningCaseId ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-2 py-3 sm:px-4 sm:py-6">
          <div
            className="absolute inset-0"
            onClick={closePlanningDialog}
          />

          <div className="relative z-10 max-h-[94vh] w-full max-w-5xl overflow-y-auto rounded-3xl border border-white/10 bg-zinc-950 shadow-2xl">
            <div className="sticky top-0 z-20 flex items-center justify-between border-b border-white/10 bg-zinc-950/95 px-5 py-4 backdrop-blur">
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Dispatch planning</p>
                <h3 className="mt-1 text-lg font-semibold text-white">{planningCaseId}</h3>
              </div>

              <button
                className="rounded-xl border border-border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-foreground transition hover:bg-muted hover:text-foreground"
                onClick={closePlanningDialog}
              >
                Close
              </button>
            </div>

            <div className="p-4">
              <Graph2Panel
                caseId={planningCaseId}
                title={`Dispatch plan for ${planningCaseId}`}
                onCommitted={async () => {
                  await refresh()
                }}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
