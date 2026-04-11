'use client'

import type { GeoPoint } from '@/lib/types'

type Marker = {
  id: string
  label: string
  subtitle?: string
  tone: 'incident' | 'team' | 'resource' | 'dispatch'
  point: GeoPoint | null
}

const toneStyles: Record<Marker['tone'], string> = {
  incident: 'bg-rose-400 ring-rose-200/60',
  team: 'bg-emerald-400 ring-emerald-200/60',
  resource: 'bg-sky-400 ring-sky-200/60',
  dispatch: 'bg-amber-300 ring-amber-100/70',
}

export function TacticalMap({
  title,
  markers,
  emptyMessage = 'Map points appear here once incidents, teams, or resources have coordinates.',
}: {
  title: string
  markers: Marker[]
  emptyMessage?: string
}) {
  const points = markers.filter((item) => item.point)

  if (points.length === 0) {
    return (
      <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <span className="rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-500">
            0 mapped
          </span>
        </div>
        <div className="mt-4 flex min-h-[320px] items-center justify-center rounded-[1.25rem] border border-dashed border-white/10 bg-[linear-gradient(180deg,rgba(148,163,184,0.04),rgba(15,23,42,0.3))] px-8 text-center text-sm leading-6 text-slate-500">
          {emptyMessage}
        </div>
      </div>
    )
  }

  const lats = points.map((item) => item.point!.lat)
  const lngs = points.map((item) => item.point!.lng)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLng = Math.min(...lngs)
  const maxLng = Math.max(...lngs)
  const latSpan = Math.max(maxLat - minLat, 0.1)
  const lngSpan = Math.max(maxLng - minLng, 0.1)

  return (
    <div className="rounded-[1.5rem] border border-white/8 bg-slate-950/45 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="rounded-full border border-white/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-500">
          {points.length} mapped
        </span>
      </div>
      <div className="mt-4 overflow-hidden rounded-[1.25rem] border border-white/8 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.18),_transparent_35%),linear-gradient(180deg,rgba(15,23,42,0.9),rgba(2,6,23,0.96))]">
        <div className="relative min-h-[340px] bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] bg-[size:56px_56px]">
          <div className="absolute inset-x-0 top-0 flex items-center justify-between px-4 py-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">
            <span>North</span>
            <span>Tactical map surface</span>
          </div>
          {points.map((marker) => {
            const x = (((marker.point!.lng - minLng) / lngSpan) * 82) + 8
            const y = (((maxLat - marker.point!.lat) / latSpan) * 72) + 12
            return (
              <div
                key={marker.id}
                className="absolute -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${x}%`, top: `${y}%` }}
              >
                <div className={`h-3.5 w-3.5 rounded-full ring-4 ${toneStyles[marker.tone]}`} />
                <div className="mt-2 min-w-36 rounded-xl border border-white/10 bg-slate-950/90 px-3 py-2 shadow-[0_10px_30px_rgba(0,0,0,0.28)]">
                  <p className="text-xs font-semibold text-stone-100">{marker.label}</p>
                  {marker.subtitle ? <p className="mt-1 text-[11px] leading-5 text-slate-400">{marker.subtitle}</p> : null}
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
        <Legend tone="incident" label="Incidents" />
        <Legend tone="team" label="Teams" />
        <Legend tone="resource" label="Resources" />
        <Legend tone="dispatch" label="Dispatches" />
      </div>
    </div>
  )
}

function Legend({ tone, label }: { tone: Marker['tone']; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/8 bg-white/4 px-3 py-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${toneStyles[tone].split(' ')[0]}`} />
      {label}
    </span>
  )
}
