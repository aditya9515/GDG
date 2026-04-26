'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { AboutButton, PageHeader } from '@/components/shared/mono-ui'
import { Input } from '@/components/ui/input'
import { createTeam, deleteTeam, listTeams } from '@/lib/api'
import { parseOptionalGeo, parseTags } from '@/lib/form-utils'
import type { Team } from '@/lib/types'

const TEAMS_PER_PAGE = 10

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
  const [page, setPage] = useState(1)

  useEffect(() => {
    if (!user) return
    void refresh()
  }, [user, search])

  useEffect(() => {
    setPage(1)
  }, [search])

  async function refresh() {
    if (!user) return
    try {
      setItems(await listTeams(user, search))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load teams.')
    }
  }

  async function addTeam() {
    if (!user) return

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
    if (!user) return

    const ok = window.confirm(`Remove team ${team.display_name}? Existing dispatches keep their audit history.`)
    if (!ok) return

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

  const totalPages = Math.max(1, Math.ceil(items.length / TEAMS_PER_PAGE))

  const visibleItems = useMemo(() => {
    const start = (page - 1) * TEAMS_PER_PAGE
    return items.slice(start, start + TEAMS_PER_PAGE)
  }, [items, page])

  const pageNumbers = Array.from({ length: totalPages }, (_, index) => index + 1)

  return (
    <div className="space-y-2">
      <PageHeader
        eyebrow="Teams"
        title="Response teams"
        description={
          <>
            <p>Create capable teams, keep their base/current map points clean, and remove stale demo data quickly.</p>
            {message ? <p className="mt-2 text-foreground">{message}</p> : null}
          </>
        }
        about="Response teams are deployable groups with capabilities, availability, service radius, and map locations. Graph 2 uses these fields to decide which teams can realistically respond."
      >
        <Input
          className="w-full xl:w-72"
          placeholder="Search teams..."
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
            <h2 className="text-xl font-semibold text-white">Add team</h2>
            <AboutButton>
              Add a deployable team with capabilities, service radius, and map location. These details affect whether Graph 2 can recommend the team for a case.
            </AboutButton>
          </div>

          <div className="mt-4 grid gap-2">
            <input
              className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none"
              placeholder="Team name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
            />
            <input
              className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none"
              placeholder="Capabilities: ambulance, water rescue, logistics"
              value={capabilities}
              onChange={(event) => setCapabilities(event.target.value)}
            />
            <input
              className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none"
              placeholder="Base label / address"
              value={baseLabel}
              onChange={(event) => setBaseLabel(event.target.value)}
            />

            <div className="grid gap-2 sm:grid-cols-3">
              <input
                className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none"
                placeholder="Lat"
                value={baseLat}
                onChange={(event) => setBaseLat(event.target.value)}
              />
              <input
                className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none"
                placeholder="Lng"
                value={baseLng}
                onChange={(event) => setBaseLng(event.target.value)}
              />
              <input
                className="rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none"
                placeholder="Radius km"
                value={serviceRadius}
                onChange={(event) => setServiceRadius(event.target.value)}
              />
            </div>

            <button
              className="rounded-xl border border-foreground bg-foreground px-4 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-background transition hover:bg-foreground/90 disabled:opacity-50"
              disabled={busy || displayName.trim().length < 2}
              onClick={() => void addTeam()}
            >
              {busy ? 'Creating...' : 'Create team'}
            </button>
          </div>
        </div>

        <div className="motion-rise motion-delay-2">
          <TacticalMap title="Team coverage" markers={markers} />
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
              {items.length} teams total
            </p>
            <AboutButton>
              The team list is the current deployable roster. Search, inspect capabilities, verify mapped bases, and remove stale teams that should not be considered for dispatch.
            </AboutButton>
          </div>
        </div>

        {visibleItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 px-4 py-8 text-sm text-slate-500">
            No teams found.
          </div>
        ) : (
          <div className="grid gap-2 xl:grid-cols-2">
            {visibleItems.map((item) => (
              <article key={item.team_id} className="min-w-0 rounded-2xl border border-white/10 bg-black/35 p-3 sm:p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <h3 className="text-lg font-semibold text-white">{item.display_name}</h3>
                    <p className="mt-1 text-sm text-slate-400">
                      {item.capability_tags.length > 0 ? item.capability_tags.join(', ') : 'General response'}
                    </p>
                  </div>

                  <button
                    className="rounded-xl border border-border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-foreground transition hover:bg-muted hover:text-foreground"
                    onClick={() => void removeTeam(item)}
                  >
                    Remove
                  </button>
                </div>

                <div className="mt-4 grid gap-2 text-sm text-slate-300">
                  <p>
                    <span className="text-slate-500">Base:</span> {item.base_label || 'Location pending'}
                  </p>
                  <p>
                    <span className="text-slate-500">Radius:</span> {item.service_radius_km} km
                  </p>
                  <p>
                    <span className="text-slate-500">Status:</span> {item.availability_status}
                  </p>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
