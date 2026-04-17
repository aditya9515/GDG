'use client'

import { useEffect, useMemo, useState } from 'react'

import { Graph2Panel } from '@/components/dispatch/graph2-panel'
import { useAuth } from '@/components/providers/auth-provider'
import { deleteDispatch, listDispatches, listIncidents } from '@/lib/api'
import type { AssignmentDecision, CaseRecord } from '@/lib/types'

export default function DispatchPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<AssignmentDecision[]>([])
  const [incidents, setIncidents] = useState<CaseRecord[]>([])
  const [search, setSearch] = useState('')
  const [selectedCaseId, setSelectedCaseId] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!user) {
      return
    }
    void refresh()
  }, [user, search])

  async function refresh() {
    if (!user) {
      return
    }
    try {
      const [dispatches, nextIncidents] = await Promise.all([listDispatches(user, search), listIncidents(user)])
      setItems(dispatches)
      setIncidents(nextIncidents)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load dispatch board.')
    }
  }

  async function removeDispatch(dispatch: AssignmentDecision) {
    if (!user) {
      return
    }
    const ok = window.confirm(`Remove dispatch ${dispatch.assignment_id}? Team load and reserved stock will be restored where possible.`)
    if (!ok) {
      return
    }
    await deleteDispatch(dispatch.assignment_id, user)
    setItems((current) => current.filter((item) => item.assignment_id !== dispatch.assignment_id))
  }

  const openIncidents = useMemo(
    () => incidents.filter((incident) => !['CLOSED', 'MERGED'].includes(incident.status)),
    [incidents],
  )

  return (
    <div className="space-y-2">
      <header className="border border-white/14 bg-black/35 p-4">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Dispatch board</p>
        <div className="mt-2 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-4xl font-semibold tracking-[-0.05em] text-white">Assignments</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              Confirmed dispatches stay auditable here. New dispatches are created from incidents through Graph 2.
            </p>
            {message ? <p className="mt-2 text-sm text-amber-100">{message}</p> : null}
          </div>
          <input
            className="border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Search dispatches..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </header>

      <section className="grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Create from incident</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Run Graph 2</h2>
          <select
            className="mt-4 w-full border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none focus:border-white/25"
            value={selectedCaseId}
            onChange={(event) => setSelectedCaseId(event.target.value)}
          >
            <option value="">Select incident</option>
            {openIncidents.map((incident) => (
              <option key={incident.case_id} value={incident.case_id}>
                {incident.case_id} | {incident.urgency} | {incident.location_text || 'location pending'}
              </option>
            ))}
          </select>
          <p className="mt-3 text-sm leading-6 text-slate-500">
            Graph 2 checks missing location, capability conflicts, availability, resource stock, route ETA, then pauses if it needs operator answers.
          </p>
        </div>
        <Graph2Panel caseId={selectedCaseId || null} onCommitted={refresh} />
      </section>

      <section className="grid gap-2 xl:grid-cols-2">
        {items.map((item) => (
          <article key={item.assignment_id} className="border border-white/10 bg-black/35 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">{item.assignment_id}</h2>
                <p className="mt-2 text-sm text-slate-400">
                  Incident {item.case_id} | Team {item.team_id ?? 'Unknown'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className="border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                  {item.status}
                </span>
                <button
                  className="border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black"
                  onClick={() => void removeDispatch(item)}
                >
                  Remove
                </button>
              </div>
            </div>
            <p className="mt-3 text-sm text-slate-300">
              ETA {item.eta_minutes ?? 'Unknown'} min | Match {Math.round(item.match_score * 100)}%
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Volunteers {item.volunteer_ids.join(', ') || 'None'} | Resources{' '}
              {item.resource_allocations.map((resource) => resource.resource_type).join(', ') || 'None'}
            </p>
          </article>
        ))}
        {items.length === 0 ? (
          <div className="border border-dashed border-white/10 p-6 text-sm text-slate-500">
            No dispatches match this search. Select an incident above to create one through Graph 2.
          </div>
        ) : null}
      </section>
    </div>
  )
}

