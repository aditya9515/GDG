'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { createVolunteer, deleteVolunteer, listTeams, listVolunteers } from '@/lib/api'
import { parseOptionalGeo, parseTags } from '@/lib/form-utils'
import type { Team, Volunteer } from '@/lib/types'

export default function VolunteersPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<Volunteer[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [teamId, setTeamId] = useState('')
  const [roleTags, setRoleTags] = useState('')
  const [skills, setSkills] = useState('')
  const [homeLabel, setHomeLabel] = useState('')
  const [lat, setLat] = useState('')
  const [lng, setLng] = useState('')
  const [capacity, setCapacity] = useState('1')

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
      const [volunteers, nextTeams] = await Promise.all([listVolunteers(user, search), listTeams(user)])
      setItems(volunteers)
      setTeams(nextTeams)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load volunteers.')
    }
  }

  async function addVolunteer() {
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
      await createVolunteer(
        {
          display_name: displayName.trim(),
          team_id: teamId || null,
          role_tags: parseTags(roleTags),
          skills: parseTags(skills),
          home_base_label: homeLabel.trim() || 'Location pending',
          home_base: geo.geo,
          current_geo: geo.geo,
          availability_status: 'AVAILABLE',
          max_concurrent_assignments: Number(capacity) || 1,
        },
        user,
      )
      setDisplayName('')
      setTeamId('')
      setRoleTags('')
      setSkills('')
      setHomeLabel('')
      setLat('')
      setLng('')
      setCapacity('1')
      setMessage('Volunteer created.')
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create volunteer.')
    } finally {
      setBusy(false)
    }
  }

  async function removeVolunteer(volunteer: Volunteer) {
    if (!user) {
      return
    }
    const ok = window.confirm(`Remove volunteer ${volunteer.display_name}? They will be detached from teams and dispatch records.`)
    if (!ok) {
      return
    }
    await deleteVolunteer(volunteer.volunteer_id, user)
    setItems((current) => current.filter((item) => item.volunteer_id !== volunteer.volunteer_id))
  }

  const markers = useMemo(
    () =>
      items.map((item) => ({
        id: item.volunteer_id,
        label: item.display_name,
        subtitle: `${item.skills.slice(0, 3).join(', ') || 'General volunteer'}`,
        tone: 'team' as const,
        point: item.current_geo ?? item.home_base,
      })),
    [items],
  )

  return (
    <div className="space-y-2">
      <header className="border border-white/14 bg-black/35 p-4">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Team members</p>
        <div className="mt-2 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h1 className="text-4xl font-semibold tracking-[-0.05em] text-white">Volunteers</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
              Add individual responders, assign them to teams, and keep their capability/location records searchable.
            </p>
            {message ? <p className="mt-2 text-sm text-amber-100">{message}</p> : null}
          </div>
          <input
            className="border border-white/10 bg-black/45 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-white/25"
            placeholder="Search volunteers..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </header>

      <section className="grid gap-2 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="surface-card p-4">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Quick create</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Add volunteer</h2>
          <div className="mt-4 grid gap-2">
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Name / display name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            <select className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" value={teamId} onChange={(event) => setTeamId(event.target.value)}>
              <option value="">No team yet</option>
              {teams.map((team) => (
                <option key={team.team_id} value={team.team_id}>{team.display_name}</option>
              ))}
            </select>
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Roles: medic, driver, responder" value={roleTags} onChange={(event) => setRoleTags(event.target.value)} />
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Skills/certifications" value={skills} onChange={(event) => setSkills(event.target.value)} />
            <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Home/current location label" value={homeLabel} onChange={(event) => setHomeLabel(event.target.value)} />
            <div className="grid grid-cols-3 gap-2">
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lat" value={lat} onChange={(event) => setLat(event.target.value)} />
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lng" value={lng} onChange={(event) => setLng(event.target.value)} />
              <input className="border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Capacity" value={capacity} onChange={(event) => setCapacity(event.target.value)} />
            </div>
            <button
              className="border border-white/15 bg-white px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-black transition hover:bg-zinc-200 disabled:opacity-50"
              disabled={busy || displayName.trim().length < 2}
              onClick={() => void addVolunteer()}
            >
              {busy ? 'Creating...' : 'Create volunteer'}
            </button>
          </div>
        </div>
        <TacticalMap title="Volunteer check-ins" markers={markers} />
      </section>

      <section className="grid gap-2 xl:grid-cols-2">
        {items.map((item) => (
          <article key={item.volunteer_id} className="border border-white/10 bg-black/35 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">{item.display_name}</h2>
                <p className="mt-2 text-sm text-slate-400">{item.home_base_label}</p>
              </div>
              <button
                className="border border-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-white transition hover:bg-white hover:text-black"
                onClick={() => void removeVolunteer(item)}
              >
                Remove
              </button>
            </div>
            <p className="mt-3 text-sm text-slate-300">Team {item.team_id ?? 'Unassigned'} | Skills {item.skills.join(', ') || 'None'}</p>
            <p className="mt-2 text-xs text-slate-500">
              {item.availability_status} | Active {item.active_assignments} | Capacity {item.max_concurrent_assignments}
            </p>
          </article>
        ))}
        {items.length === 0 ? (
          <div className="border border-dashed border-white/10 p-6 text-sm text-slate-500">No volunteers match this search.</div>
        ) : null}
      </section>
    </div>
  )
}

