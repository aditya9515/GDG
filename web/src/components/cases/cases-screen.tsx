'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { Graph2Panel } from '@/components/dispatch/graph2-panel'
import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { useCaseManager } from '@/hooks/use-case-manager'
import { listIncidents } from '@/lib/api'
import type { CaseRecord } from '@/lib/types'

import { UrgencyBadge } from './urgency-badge'

const filters = ['ALL', 'CRITICAL', 'HIGH', 'NEEDS_REVIEW', 'UNMAPPED'] as const

type CaseFilter = (typeof filters)[number]

export function CasesScreen() {
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
    if (!user) {
      return
    }
    void refresh()
  }, [user, search])

  const filteredIncidents = useMemo(() => {
    if (filter === 'ALL') {
      return incidents
    }
    if (filter === 'NEEDS_REVIEW') {
      return incidents.filter((incident) => incident.status === 'NEEDS_REVIEW' || incident.location_confidence === 'UNKNOWN')
    }
    if (filter === 'UNMAPPED') {
      return incidents.filter((incident) => !incident.geo)
    }
    return incidents.filter((incident) => incident.urgency === filter)
  }, [filter, incidents])

  const markers = useMemo(
    () =>
      incidents.map((incident) => ({
        id: incident.case_id,
        label: incident.case_id,
        subtitle: `${incident.urgency} | ${incident.location_text || 'Location pending'}`,
        tone: 'incident' as const,
        point: incident.geo,
      })),
    [incidents],
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

  return (
    <div className="space-y-2">
      <header className="motion-rise border border-white/14 bg-black/35 p-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Case registry</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-[-0.05em] text-white md:text-5xl">Cases</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
              Add, map, open, and remove incidents for the active organization. Bulk CSV, PDF, and image parsing stays in Imports.
            </p>
            {message ? <p className="mt-3 text-sm text-rose-200">{message}</p> : null}
          </div>
          <button
            className="border border-white/15 px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black disabled:opacity-50"
            disabled={loading}
            onClick={() => void refresh()}
          >
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        </div>
      </header>

      <section className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_27rem]">
        <div className="surface-card motion-rise motion-delay-1 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Create case</p>
              <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-white">Quick single incident</h2>
            </div>
            <span className="border border-white/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.16em] text-slate-400">
              Manual
            </span>
          </div>
          <textarea
            className="mt-4 min-h-28 w-full resize-none border border-white/10 bg-black/40 px-3 py-2 text-sm leading-5 text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Raw report, call note, or copied message. Example: Ambulance needed for pregnant woman in labour, road flooded near Ward 4."
            value={rawInput}
            onChange={(event) => setRawInput(event.target.value)}
          />
          <div className="mt-2 grid gap-2 md:grid-cols-[1.2fr_0.8fr_0.8fr]">
            <input
              className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder="Location label or address"
              value={locationText}
              onChange={(event) => setLocationText(event.target.value)}
            />
            <input
              className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder="Latitude"
              value={lat}
              onChange={(event) => setLat(event.target.value)}
            />
            <input
              className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder="Longitude"
              value={lng}
              onChange={(event) => setLng(event.target.value)}
            />
          </div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs leading-5 text-slate-500">Coordinates are optional; valid pins make the case visible on the map immediately.</p>
            <button
              className="border border-white/15 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
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
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">All cases</p>
            <h2 className="mt-2 text-xl font-semibold tracking-[-0.03em] text-white">{filteredIncidents.length} visible</h2>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              className="min-w-64 border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
              placeholder="Search cases..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {filters.map((item) => (
              <button
                key={item}
                className={`border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] transition ${
                  filter === item
                    ? 'border-white bg-white text-black'
                    : 'border-white/10 text-slate-400 hover:border-white/25 hover:bg-white hover:text-black'
                }`}
                onClick={() => setFilter(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 grid gap-2">
          {filteredIncidents.map((incident) => (
            <article key={incident.case_id} className="border border-white/[0.08] bg-white/[0.025] p-3 transition hover:border-white/15 hover:bg-white/[0.045]">
              <div className="grid gap-3 xl:grid-cols-[11rem_minmax(0,1fr)_14rem] xl:items-center">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <UrgencyBadge urgency={incident.urgency} />
                    <span className="border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                      {incident.status}
                    </span>
                  </div>
                  <p className="mt-2 text-sm font-semibold text-white">{incident.case_id}</p>
                  <p className="mt-1 text-[11px] text-slate-600">Score {incident.priority_score ?? 'pending'}</p>
                </div>

                <div className="min-w-0">
                  <p className="line-clamp-2 text-sm leading-5 text-slate-300">{incident.raw_input}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                    <span className="border border-white/10 px-2 py-1 uppercase tracking-[0.14em]">{incident.location_confidence}</span>
                    <span className="truncate border border-white/10 px-2 py-1">{incident.location_text || 'No location yet'}</span>
                    <span className="border border-white/10 px-2 py-1">{incident.geo ? `${incident.geo.lat.toFixed(4)}, ${incident.geo.lng.toFixed(4)}` : 'Unmapped'}</span>
                  </div>
                </div>

                <div className="flex gap-2 xl:justify-end">
                  <Link
                    className="border border-white/15 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black"
                    href={`/cases/${incident.case_id}`}
                  >
                    Open
                  </Link>
                  <button
                    className="border border-white/15 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black"
                    onClick={() => setPlanningCaseId((current) => (current === incident.case_id ? null : incident.case_id))}
                  >
                    Plan
                  </button>
                  <button
                    aria-label={`Remove ${incident.case_id}`}
                    className="border border-white/15 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-white transition hover:bg-white hover:text-black disabled:opacity-50"
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
            <div className="border border-dashed border-white/10 p-8 text-center text-sm text-slate-500">
              {incidents.length === 0 ? 'No cases exist in this organization yet.' : 'No cases match this filter.'}
            </div>
          ) : null}
        </div>
      </section>

      {planningCaseId ? (
        <Graph2Panel
          caseId={planningCaseId}
          title={`Dispatch plan for ${planningCaseId}`}
          onCommitted={refresh}
        />
      ) : null}
    </div>
  )
}
