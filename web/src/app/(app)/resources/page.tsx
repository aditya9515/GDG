'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { createResource, deleteResource, listResources, listTeams } from '@/lib/api'
import { parseOptionalGeo, parseTags } from '@/lib/form-utils'
import type { ResourceInventory, Team } from '@/lib/types'

export default function ResourcesPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<ResourceInventory[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [resourceType, setResourceType] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [locationLabel, setLocationLabel] = useState('')
  const [lat, setLat] = useState('')
  const [lng, setLng] = useState('')
  const [owningTeamId, setOwningTeamId] = useState('')
  const [constraints, setConstraints] = useState('')

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
      const [resources, nextTeams] = await Promise.all([listResources(user, search), listTeams(user)])
      setItems(resources)
      setTeams(nextTeams)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load resources.')
    }
  }

  async function addResource() {
    if (!user) {
      return
    }
    const geo = parseOptionalGeo(lat, lng)
    if (!geo.ok) {
      setMessage(geo.message)
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      await createResource(
        {
          owning_team_id: owningTeamId || null,
          resource_type: resourceType.trim(),
          quantity_available: Number(quantity) || 0,
          location_label: locationLabel.trim() || 'Location pending',
          location: geo.geo,
          current_geo: geo.geo,
          current_label: locationLabel.trim() || null,
          constraints: parseTags(constraints),
        },
        user,
      )
      setResourceType('')
      setQuantity('1')
      setLocationLabel('')
      setLat('')
      setLng('')
      setOwningTeamId('')
      setConstraints('')
      setMessage('Resource created.')
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create resource.')
    } finally {
      setBusy(false)
    }
  }

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
    <div className="space-y-2">
      <header className="border border-white/14 bg-black/35 p-4">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Resources</p>
        <div className="mt-2 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-4xl font-semibold tracking-[-0.05em] text-white">Inventory and assets</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              Add vehicles, kits, stock, fuel, shelter items, and field equipment with map-ready depot locations.
            </p>
            {message ? <p className="mt-2 text-sm text-amber-100">{message}</p> : null}
          </div>
          <input
            className="border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Search resources..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </header>

      <section className="grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Quick create</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Add resource</h2>
          <div className="mt-4 grid gap-2">
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Resource type: ambulance, water truck, food packs" value={resourceType} onChange={(event) => setResourceType(event.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Quantity" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
              <select className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" value={owningTeamId} onChange={(event) => setOwningTeamId(event.target.value)}>
                <option value="">No owner team</option>
                {teams.map((team) => (
                  <option key={team.team_id} value={team.team_id}>{team.display_name}</option>
                ))}
              </select>
            </div>
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Depot/current location label" value={locationLabel} onChange={(event) => setLocationLabel(event.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lat" value={lat} onChange={(event) => setLat(event.target.value)} />
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lng" value={lng} onChange={(event) => setLng(event.target.value)} />
            </div>
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Constraints: driver license, cold chain, fuel" value={constraints} onChange={(event) => setConstraints(event.target.value)} />
            <button
              className="border border-white/15 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:opacity-50"
              disabled={busy || resourceType.trim().length < 2}
              onClick={() => void addResource()}
            >
              {busy ? 'Creating...' : 'Create resource'}
            </button>
          </div>
        </div>
        <TacticalMap title="Resource locations" markers={markers} />
      </section>

      <section className="grid gap-2 xl:grid-cols-2">
        {items.map((item) => (
          <article key={item.resource_id} className="border border-white/10 bg-black/35 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">{item.resource_type}</h2>
                <p className="mt-2 text-sm text-slate-400">{item.current_label || item.location_label}</p>
              </div>
              <button
                className="border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black"
                onClick={() => void removeResource(item)}
              >
                Remove
              </button>
            </div>
            <p className="mt-3 text-sm text-slate-300">Quantity {item.quantity_available} | Owner {item.owning_team_id ?? 'Unassigned'}</p>
            <p className="mt-2 text-xs text-slate-500">{item.constraints.join(', ') || 'No extra constraints'}</p>
          </article>
        ))}
        {items.length === 0 ? (
          <div className="border border-dashed border-white/10 p-6 text-sm text-slate-500">No resources match this search.</div>
        ) : null}
      </section>
    </div>
  )
}

