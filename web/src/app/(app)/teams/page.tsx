'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { createTeam, deleteTeam, listTeams } from '@/lib/api'
import { parseOptionalGeo, parseTags } from '@/lib/form-utils'
import type { Team } from '@/lib/types'

export default function TeamsPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<Team[]>([])
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [capabilities, setCapabilities] = useState('')
  const [baseLabel, setBaseLabel] = useState('')
  const [baseLat, setBaseLat] = useState('')
  const [baseLng, setBaseLng] = useState('')
  const [serviceRadius, setServiceRadius] = useState('30')

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
      setItems(await listTeams(user, search))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load teams.')
    }
  }

  async function addTeam() {
    if (!user) {
      return
    }
    const geo = parseOptionalGeo(baseLat, baseLng)
    if (!geo.ok) {
      setMessage(geo.message)
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      await createTeam(
        {
          display_name: displayName.trim(),
          capability_tags: parseTags(capabilities),
          service_radius_km: Number(serviceRadius) || 30,
          base_label: baseLabel.trim() || 'Location pending',
          base_geo: geo.geo,
          current_geo: geo.geo,
          current_label: baseLabel.trim() || null,
          availability_status: 'AVAILABLE',
        },
        user,
      )
      setDisplayName('')
      setCapabilities('')
      setBaseLabel('')
      setBaseLat('')
      setBaseLng('')
      setServiceRadius('30')
      setMessage('Team created.')
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create team.')
    } finally {
      setBusy(false)
    }
  }

  async function removeTeam(team: Team) {
    if (!user) {
      return
    }
    const ok = window.confirm(`Remove team ${team.display_name}? Existing dispatches keep their audit history.`)
    if (!ok) {
      return
    }
    await deleteTeam(team.team_id, user)
    setItems((current) => current.filter((item) => item.team_id !== team.team_id))
  }

  const markers = useMemo(
    () =>
      items.map((item) => ({
        id: item.team_id,
        label: item.display_name,
        subtitle: `${item.capability_tags.slice(0, 3).join(', ') || 'General response'}`,
        tone: 'team' as const,
        point: item.current_geo ?? item.base_geo,
      })),
    [items],
  )

  return (
    <div className="space-y-2">
      <header className="border border-white/14 bg-black/35 p-4">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Teams</p>
        <div className="mt-2 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-4xl font-semibold tracking-[-0.05em] text-white">Response teams</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              Create capable teams, keep their base/current map points clean, and remove stale demo data quickly.
            </p>
            {message ? <p className="mt-2 text-sm text-amber-100">{message}</p> : null}
          </div>
          <input
            className="border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Search teams..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </header>

      <section className="grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Quick create</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Add team</h2>
          <div className="mt-4 grid gap-2">
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Team name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Capabilities: ambulance, water rescue, logistics" value={capabilities} onChange={(event) => setCapabilities(event.target.value)} />
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Base label / address" value={baseLabel} onChange={(event) => setBaseLabel(event.target.value)} />
            <div className="grid grid-cols-3 gap-2">
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lat" value={baseLat} onChange={(event) => setBaseLat(event.target.value)} />
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lng" value={baseLng} onChange={(event) => setBaseLng(event.target.value)} />
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Radius km" value={serviceRadius} onChange={(event) => setServiceRadius(event.target.value)} />
            </div>
            <button
              className="border border-white/15 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:opacity-50"
              disabled={busy || displayName.trim().length < 2}
              onClick={() => void addTeam()}
            >
              {busy ? 'Creating...' : 'Create team'}
            </button>
          </div>
        </div>
        <TacticalMap title="Team coverage" markers={markers} />
      </section>

      <section className="grid gap-2 xl:grid-cols-2">
        {items.map((item) => (
          <article key={item.team_id} className="border border-white/10 bg-black/35 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">{item.display_name}</h2>
                <p className="mt-2 text-sm text-slate-400">{item.base_label}</p>
              </div>
              <button
                className="border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black"
                onClick={() => void removeTeam(item)}
              >
                Remove
              </button>
            </div>
            <p className="mt-3 text-sm text-slate-300">Capabilities: {item.capability_tags.join(', ') || 'General response'}</p>
            <p className="mt-2 text-xs text-slate-500">
              {item.availability_status} | Members {item.member_ids.length} | Radius {item.service_radius_km} km | Active {item.active_dispatches}
            </p>
          </article>
        ))}
        {items.length === 0 ? (
          <div className="border border-dashed border-white/10 p-6 text-sm text-slate-500">No teams match this search.</div>
        ) : null}
      </section>
    </div>
  )
}

