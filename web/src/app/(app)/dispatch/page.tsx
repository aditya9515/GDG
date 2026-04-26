'use client'

import { useEffect, useMemo, useState } from 'react'

import { BatchDispatchPlanner } from '@/components/dispatch/batch-dispatch-planner'
import { Graph2Panel } from '@/components/dispatch/graph2-panel'
import { useAuth } from '@/components/providers/auth-provider'
import { BusyOverlay } from '@/components/shared/loading-state'
import { AboutButton, PageHeader } from '@/components/shared/mono-ui'
import { Input } from '@/components/ui/input'
import { deleteDispatch, listDispatches, listIncidents } from '@/lib/api'
import { humanizeToken } from '@/lib/format'
import type { AssignmentDecision, CaseRecord } from '@/lib/types'

export default function DispatchPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<AssignmentDecision[]>([])
  const [incidents, setIncidents] = useState<CaseRecord[]>([])
  const [search, setSearch] = useState('')
  const [selectedCaseId, setSelectedCaseId] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = 10

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
    setLoading(true)
    try {
      const [dispatches, nextIncidents] = await Promise.all([listDispatches(user, search), listIncidents(user)])
      setItems(dispatches)
      setIncidents(nextIncidents)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load dispatch board.')
    } finally {
      setLoading(false)
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

  const totalPages = Math.max(1, Math.ceil(items.length / pageSize))

  const paginatedItems = useMemo(() => {
    const start = (page - 1) * pageSize
    return items.slice(start, start + pageSize)
  }, [items, page])

  useEffect(() => {
    setPage(1)
  }, [items.length, search])

  return (
    <div className="relative space-y-2">
      <BusyOverlay active={loading} title="Loading dispatch board" message="Refreshing dispatches and open incidents." />
      <PageHeader
        eyebrow="Dispatch board"
        title="Assignments"
        description={
          <>
            <p>Plan all open cases together, then commit one selected case or the full global dispatch batch.</p>
            {message ? <p className="mt-2 text-foreground">{message}</p> : null}
          </>
        }
        about="This board shows committed dispatch assignments and the primary batch planning workspace. Batch planning allocates scarce teams and resources across all open cases; single-case planning below is only a focused fallback."
      >
        <Input
          className="w-full xl:w-72"
          placeholder="Search dispatches..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </PageHeader>

      <div className="motion-rise motion-delay-1">
        <BatchDispatchPlanner incidents={openIncidents} onCommitted={refresh} />
      </div>

      <section className="motion-rise motion-delay-2 grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Create from incident</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-white">Single-case planning</h2>
            <AboutButton>
              Single-case planning creates a focused dispatch recommendation for one incident. It is useful for manual follow-up, but it does not globally optimize scarce assets across all cases.
            </AboutButton>
          </div>
          <select
            className="mt-4 w-full rounded-xl border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none focus:border-white/25"
            value={selectedCaseId}
            onChange={(event) => setSelectedCaseId(event.target.value)}
          >
            <option value="">Select incident</option>
            {openIncidents.map((incident) => (
              <option key={incident.case_id} value={incident.case_id}>
                {incident.case_id} | {humanizeToken(incident.urgency)} | {incident.location_text || 'location pending'}
              </option>
            ))}
          </select>
          <p className="mt-3 text-sm leading-6 text-slate-500">
            Use this only when you intentionally want to plan one incident outside the global allocation board.
          </p>
        </div>
        <Graph2Panel caseId={selectedCaseId || null} onCommitted={refresh} />
      </section>

      <div className="motion-rise motion-delay-2 space-y-3">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Committed assignments</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-white">Confirmed dispatches</h2>
          <AboutButton>
            These are confirmed dispatch records. They reflect committed teams, volunteers, resources, ETA details, and status after an operator confirms a plan.
          </AboutButton>
          </div>
        </div>
        <div className="motion-rise motion-delay-1 flex flex-wrap gap-2">
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((num) => (
            <button
              key={num}
              className={`min-w-[34px] rounded-xl border px-3 py-1 text-xs font-semibold transition ${
                page === num
                  ? 'border-foreground bg-foreground text-background'
                  : 'border-border text-foreground hover:bg-muted hover:text-foreground'
              }`}
              onClick={() => setPage(num)}
            >
              {num}
            </button>
          ))}
        </div>

        <section className="motion-rise motion-delay-2 grid gap-2 xl:grid-cols-2">
        {paginatedItems.map((item) => (
          <article key={item.assignment_id} className="min-w-0 rounded-2xl border border-white/10 bg-black/35 p-3 sm:p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <h2 className="font-semibold text-white">{item.assignment_id}</h2>
                <p className="mt-2 text-sm text-slate-400">
                  Incident {item.case_id} | Team {item.team_id ?? 'Unknown'}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                  {humanizeToken(item.status)}
                </span>
                <button
                  className="rounded-xl border border-border px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-foreground transition hover:bg-muted hover:text-foreground"
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
              {item.resource_allocations.map((resource) => humanizeToken(resource.resource_type)).join(', ') || 'None'}
            </p>
          </article>
        ))}
        {items.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 p-6 text-sm text-slate-500">
            No dispatches match this search. Select an incident above to create one focused dispatch plan.
          </div>
        ) : null}
      </section>
      </div>
    </div>
  )
}
