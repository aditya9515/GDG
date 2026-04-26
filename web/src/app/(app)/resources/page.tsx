'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { AboutButton, PageHeader } from '@/components/shared/mono-ui'
import { Input } from '@/components/ui/input'
import { createResource, deleteResource, listResources, listTeams } from '@/lib/api'
import { parseOptionalGeo, parseTags } from '@/lib/form-utils'
import type { ResourceInventory, Team } from '@/lib/types'

const RESOURCES_PER_PAGE = 10

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
  const [page, setPage] = useState(1)

  useEffect(() => {
    if (!user) {
      return
    }
    void refresh()
  }, [user, search])

  useEffect(() => {
    setPage(1)
  }, [search])

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

  const totalPages = Math.max(1, Math.ceil(items.length / RESOURCES_PER_PAGE))

  const visibleItems = useMemo(() => {
    const start = (page - 1) * RESOURCES_PER_PAGE
    return items.slice(start, start + RESOURCES_PER_PAGE)
  }, [items, page])

  const pageNumbers = Array.from({ length: totalPages }, (_, index) => index + 1)

  return (
    <div className="space-y-2">
      <PageHeader
        eyebrow="Resources"
        title="Inventory and assets"
        description={
          <>
            <p>Add vehicles, kits, stock, fuel, shelter items, and field equipment with map-ready depot locations.</p>
            {message ? <p className="mt-2 text-foreground">{message}</p> : null}
          </>
        }
        about="Resources are counted stock, vehicles, kits, and equipment that dispatch plans may reserve or consume. Keep quantities, owner teams, constraints, and depot locations up to date before planning."
      >
        <Input
          className="w-full xl:w-72"
          placeholder="Search resources..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </PageHeader>

      <section className="motion-rise motion-delay-1 grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card p-4">
          <div className="flex items-center gap-2">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Quick create</p>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-white">Add resource</h2>
            <AboutButton>
              Add stock, kits, vehicles, or equipment here with a quantity and depot location. Dispatch confirmation can reserve or consume these resources.
            </AboutButton>
          </div>
          <div className="mt-4 grid gap-2">
            <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Resource type: ambulance, water truck, food packs" value={resourceType} onChange={(event) => setResourceType(event.target.value)} />
            <div className="grid gap-2 sm:grid-cols-2">
              <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Quantity" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
              <select className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" value={owningTeamId} onChange={(event) => setOwningTeamId(event.target.value)}>
                <option value="">No owner team</option>
                {teams.map((team) => (
                  <option key={team.team_id} value={team.team_id}>{team.display_name}</option>
                ))}
              </select>
            </div>
            <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Depot/current location label" value={locationLabel} onChange={(event) => setLocationLabel(event.target.value)} />
            <div className="grid gap-2 sm:grid-cols-2">
              <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lat" value={lat} onChange={(event) => setLat(event.target.value)} />
              <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lng" value={lng} onChange={(event) => setLng(event.target.value)} />
            </div>
            <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Constraints: driver license, cold chain, fuel" value={constraints} onChange={(event) => setConstraints(event.target.value)} />
            <button
              className="rounded-xl border border-foreground bg-foreground px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-background transition hover:bg-foreground/90 disabled:opacity-50"
              disabled={busy || resourceType.trim().length < 2}
              onClick={() => void addResource()}
            >
              {busy ? 'Creating...' : 'Create resource'}
            </button>
          </div>
        </div>

        <div className="motion-rise motion-delay-2">
          <TacticalMap title="Resource locations" markers={markers} />
        </div>
      </section>

      <section className="surface-card motion-rise motion-delay-3 p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            {pageNumbers.map((pageNumber) => (
              <button
                key={pageNumber}
                type="button"
                onClick={() => setPage(pageNumber)}
                className={`min-w-[2.2rem] rounded-xl border px-3 py-1.5 text-xs font-semibold transition ${
                  page === pageNumber
                    ? 'border-foreground bg-foreground text-background'
                    : 'border-border bg-background/70 text-foreground hover:bg-muted hover:text-foreground'
                }`}
              >
                {pageNumber}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
              {items.length} resources total
            </p>
            <AboutButton>
              This inventory list is what dispatch planning checks for available stock, ownership, constraints, and mapped supply locations.
            </AboutButton>
          </div>
        </div>

        {visibleItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 p-6 text-sm text-slate-500">
            No resources match this search.
          </div>
        ) : (
          <div className="grid gap-2 xl:grid-cols-2">
            {visibleItems.map((item) => (
              <article key={item.resource_id} className="min-w-0 rounded-2xl border border-white/10 bg-black/35 p-3 sm:p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h2 className="font-semibold text-white">{item.resource_type}</h2>
                    <p className="mt-2 text-sm text-slate-400">{item.current_label || item.location_label}</p>
                  </div>
                  <button
                    className="rounded-xl border border-border px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-foreground transition hover:bg-muted hover:text-foreground"
                    onClick={() => void removeResource(item)}
                  >
                    Remove
                  </button>
                </div>
                <p className="mt-3 text-sm text-slate-300">Quantity {item.quantity_available} | Owner {item.owning_team_id ?? 'Unassigned'}</p>
                <p className="mt-2 text-xs text-slate-500">{item.constraints.join(', ') || 'No extra constraints'}</p>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
