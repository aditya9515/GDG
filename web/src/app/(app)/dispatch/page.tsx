'use client'

import { useEffect, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { deleteDispatch, listDispatches } from '@/lib/api'
import type { AssignmentDecision } from '@/lib/types'

export default function DispatchPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<AssignmentDecision[]>([])

  useEffect(() => {
    if (!user) {
      return
    }
    void listDispatches(user).then(setItems)
  }, [user])

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

  return (
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Dispatch board</p>
        <h1 className="mt-2 text-3xl font-semibold">Confirmed and active deployments</h1>
      </header>
      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <div key={item.assignment_id} className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-stone-100">{item.assignment_id}</h2>
              <div className="flex items-center gap-2">
                <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                  {item.status}
                </span>
                <button
                  className="rounded-full border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black"
                  onClick={() => void removeDispatch(item)}
                >
                  Remove
                </button>
              </div>
            </div>
            <p className="mt-2 text-sm text-slate-400">
              Incident {item.case_id} • Team {item.team_id ?? 'Unknown'}
            </p>
            <p className="mt-2 text-sm text-slate-300">
              ETA {item.eta_minutes ?? 'Unknown'} min • Match {item.match_score}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Volunteers {item.volunteer_ids.join(', ') || 'None'} • Resources{' '}
              {item.resource_allocations.map((resource) => resource.resource_type).join(', ') || 'None'}
            </p>
          </div>
        ))}
        {items.length === 0 ? (
          <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5 text-sm text-slate-500">
            Confirm dispatches from an incident detail page to populate this board.
          </div>
        ) : null}
      </div>
    </div>
  )
}
