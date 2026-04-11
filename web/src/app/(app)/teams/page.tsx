'use client'

import { useEffect, useMemo, useState } from 'react'

import { TacticalMap } from '@/components/maps/tactical-map'
import { useAuth } from '@/components/providers/auth-provider'
import { listTeams } from '@/lib/api'
import type { Team } from '@/lib/types'

export default function TeamsPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<Team[]>([])

  useEffect(() => {
    if (!user) {
      return
    }
    void listTeams(user).then(setItems)
  }, [user])

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
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Teams</p>
        <h1 className="mt-2 text-3xl font-semibold">Response teams and operating areas</h1>
      </header>

      <TacticalMap title="Team coverage" markers={markers} />

      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <div key={item.team_id} className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-stone-100">{item.display_name}</h2>
              <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                {item.availability_status}
              </span>
            </div>
            <p className="mt-2 text-sm text-slate-400">{item.base_label}</p>
            <p className="mt-3 text-sm text-slate-300">Capabilities: {item.capability_tags.join(', ') || 'General response'}</p>
            <p className="mt-2 text-xs text-slate-500">
              Members {item.member_ids.length} • Radius {item.service_radius_km} km • Active dispatches {item.active_dispatches}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
