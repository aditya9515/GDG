'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { AboutButton, PageHeader } from '@/components/shared/mono-ui'
import { Input } from '@/components/ui/input'
import { createVolunteer, deleteVolunteer, listTeams, listVolunteers } from '@/lib/api'
import { parseOptionalGeo, parseTags } from '@/lib/form-utils'
import type { Team, Volunteer } from '@/lib/types'

const VOLUNTEERS_PER_PAGE = 10

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

  const totalPages = Math.max(1, Math.ceil(items.length / VOLUNTEERS_PER_PAGE))

  const visibleItems = useMemo(() => {
    const start = (page - 1) * VOLUNTEERS_PER_PAGE
    return items.slice(start, start + VOLUNTEERS_PER_PAGE)
  }, [items, page])

  const pageNumbers = Array.from({ length: totalPages }, (_, index) => index + 1)

  return (
    <div className="space-y-2">
      <PageHeader
        eyebrow="Team members"
        title="Volunteers"
        description={
          <>
            <p>Add individual responders, assign them to teams, and keep their capability/location records searchable.</p>
            {message ? <p className="mt-2 text-foreground">{message}</p> : null}
          </>
        }
        about="Volunteers represent individual people available for response work. Their skills, team link, capacity, availability, and mapped check-in location help determine whether a dispatch recommendation is feasible."
      >
        <Input
          className="w-full xl:w-72"
          placeholder="Search volunteers..."
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
            <h2 className="text-xl font-semibold text-white">Add volunteer</h2>
            <AboutButton>
              Add a responder with skills, team membership, capacity, and location. These fields help determine staffing fit during dispatch planning.
            </AboutButton>
          </div>
          <div className="mt-4 grid gap-2">
            <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Name / display name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            <select className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" value={teamId} onChange={(event) => setTeamId(event.target.value)}>
              <option value="">No team yet</option>
              {teams.map((team) => (
                <option key={team.team_id} value={team.team_id}>{team.display_name}</option>
              ))}
            </select>
            <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Roles: medic, driver, responder" value={roleTags} onChange={(event) => setRoleTags(event.target.value)} />
            <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Skills/certifications" value={skills} onChange={(event) => setSkills(event.target.value)} />
            <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Home/current location label" value={homeLabel} onChange={(event) => setHomeLabel(event.target.value)} />
            <div className="grid gap-2 sm:grid-cols-3">
              <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lat" value={lat} onChange={(event) => setLat(event.target.value)} />
              <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Lng" value={lng} onChange={(event) => setLng(event.target.value)} />
              <input className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none" placeholder="Capacity" value={capacity} onChange={(event) => setCapacity(event.target.value)} />
            </div>
            <button
              className="rounded-xl border border-foreground bg-foreground px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-background transition hover:bg-foreground/90 disabled:opacity-50"
              disabled={busy || displayName.trim().length < 2}
              onClick={() => void addVolunteer()}
            >
              {busy ? 'Creating...' : 'Create volunteer'}
            </button>
          </div>
        </div>

        <div className="motion-rise motion-delay-2">
          <TacticalMap title="Volunteer check-ins" markers={markers} />
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
              {items.length} volunteers total
            </p>
            <AboutButton>
              The volunteer list shows individual responders available to support teams or assignments. Keep skills and locations current for better planning.
            </AboutButton>
          </div>
        </div>

        {visibleItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 p-6 text-sm text-slate-500">
            No volunteers match this search.
          </div>
        ) : (
          <div className="grid gap-2 xl:grid-cols-2">
            {visibleItems.map((item) => (
              <article key={item.volunteer_id} className="min-w-0 rounded-2xl border border-white/10 bg-black/35 p-3 sm:p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h2 className="font-semibold text-white">{item.display_name}</h2>
                    <p className="mt-2 text-sm text-slate-400">{item.home_base_label}</p>
                  </div>
                  <button
                    className="rounded-xl border border-border px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-foreground transition hover:bg-muted hover:text-foreground"
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
          </div>
        )}
      </section>
    </div>
  )
}
