'use client'

import { useEffect, useState } from 'react'

import { useAuth } from '@/components/providers/auth-provider'
import { listVolunteers } from '@/lib/api'
import type { Volunteer } from '@/lib/types'

export default function VolunteersPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<Volunteer[]>([])

  useEffect(() => {
    if (!user) {
      return
    }
    void listVolunteers(user).then(setItems)
  }, [user])

  return (
    <div className="space-y-6">
      <header className="border-b border-white/8 pb-5">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Team members</p>
        <h1 className="mt-2 text-3xl font-semibold">Volunteer availability and skills</h1>
      </header>
      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <div key={item.volunteer_id} className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-stone-100">{item.display_name}</h2>
              <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                {item.availability_status}
              </span>
            </div>
            <p className="mt-2 text-sm text-slate-400">{item.home_base_label}</p>
            <p className="mt-3 text-sm text-slate-300">Team {item.team_id ?? 'Unassigned'} • Skills {item.skills.join(', ')}</p>
            <p className="mt-2 text-xs text-slate-500">Active assignments: {item.active_assignments}</p>
          </div>
        ))}
      </div>
    </div>
  )
}
