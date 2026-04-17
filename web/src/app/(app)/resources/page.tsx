'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { deleteResource, listResources } from '@/lib/api'
import type { ResourceInventory } from '@/lib/types'

export default function ResourcesPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<ResourceInventory[]>([])

  useEffect(() => {
    if (!user) {
      return
    }
    void listResources(user).then(setItems)
  }, [user])

  async function removeResource(resource: ResourceInventory) {
    if (!user) {
      return
    }
    const ok = window.confirm(`Remove resource ${resource.resource_type}? This also removes its capability tokens and vector records.`)
    if (!ok) {
      return
    }
    await deleteResource(resource.resource_id, user)
    setItems((current) => current.filter((item) => item.resource_id !== resource.resource_id))
  }

  const markers = useMemo(
    () =>
      items.map((item) => ({
        id: item.resource_id,
        label: item.resource_type,
        subtitle: `${item.quantity_available} available`,
        tone: 'resource' as const,
        point: item.current_geo ?? item.location,
      })),
    [items],
  )

  return (
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Resources</p>
        <h1 className="mt-2 text-3xl font-semibold">Vehicles, stock, and field assets</h1>
      </header>

      <TacticalMap title="Resource locations" markers={markers} />

      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <div key={item.resource_id} className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-stone-100">{item.resource_type}</h2>
              <div className="flex items-center gap-2">
                <p className="text-2xl font-semibold text-stone-100">{item.quantity_available}</p>
                <button
                  className="rounded-full border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black"
                  onClick={() => void removeResource(item)}
                >
                  Remove
                </button>
              </div>
            </div>
            <p className="mt-2 text-sm text-slate-400">{item.current_label || item.location_label}</p>
            <p className="mt-3 text-sm text-slate-300">Owned by {item.owning_team_id ?? 'Unassigned team'}</p>
            <p className="mt-2 text-xs text-slate-500">{item.constraints.join(', ') || 'No extra constraints'}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
