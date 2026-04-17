'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { ENABLE_GOOGLE_MAPS_UI, GOOGLE_MAPS_API_KEY } from '@/lib/config'
import type { GeoPoint } from '@/lib/types'

type Marker = {
  id: string
  label: string
  subtitle?: string
  tone: 'incident' | 'team' | 'resource' | 'dispatch'
  point: GeoPoint | null
}

type GoogleMapsWindow = Window & {
  google?: {
    maps: any
  }
}

const toneStyles: Record<Marker['tone'], string> = {
  incident: 'bg-white ring-white/50',
  team: 'bg-zinc-300 ring-white/35',
  resource: 'bg-zinc-500 ring-white/25',
  dispatch: 'bg-zinc-100 ring-white/45',
}

const toneColors: Record<Marker['tone'], string> = {
  incident: '#ffffff',
  team: '#d4d4d8',
  resource: '#71717a',
  dispatch: '#f4f4f5',
}

let googleMapsLoader: Promise<void> | null = null

function loadGoogleMaps(): Promise<void> {
  if (typeof window === 'undefined' || !ENABLE_GOOGLE_MAPS_UI) {
    return Promise.resolve()
  }
  const typedWindow = window as GoogleMapsWindow
  if (typedWindow.google?.maps) {
    return Promise.resolve()
  }
  if (googleMapsLoader) {
    return googleMapsLoader
  }

  googleMapsLoader = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-reliefops-google-maps="true"]')
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('Failed to load Google Maps.')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${GOOGLE_MAPS_API_KEY}&v=weekly`
    script.async = true
    script.defer = true
    script.dataset.reliefopsGoogleMaps = 'true'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Failed to load Google Maps.'))
    document.head.appendChild(script)
  })

  return googleMapsLoader
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
  const [mapError, setMapError] = useState<string | null>(null)

  if (points.length === 0) {
    return (
      <MapShell title={title} count={0}>
        <div className="mt-4 flex min-h-[360px] items-center justify-center rounded-[1.25rem] border border-dashed border-white/10 bg-black/20 px-8 text-center text-sm leading-6 text-slate-500">
          {emptyMessage}
        </div>
      </MapShell>
    )
  }

  if (ENABLE_GOOGLE_MAPS_UI) {
    return (
      <MapShell title={title} count={points.length}>
        <GoogleMapSurface markers={points} onError={setMapError} />
        <LegendRow />
        {mapError ? <p className="mt-3 text-xs text-amber-100">{mapError}</p> : null}
      </MapShell>
    )
  }

  return (
    <MapShell title={title} count={points.length}>
      <FallbackMapSurface markers={points} />
      <LegendRow />
    </MapShell>
  )
}

function MapShell({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="surface-card p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold tracking-[-0.03em] text-white">{title}</h2>
        <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-slate-500">
          {count} mapped
        </span>
      </div>
      {children}
    </div>
  )
}

function GoogleMapSurface({
  markers,
  onError,
}: {
  markers: Marker[]
  onError: (message: string | null) => void
}) {
  const mapRef = useRef<HTMLDivElement | null>(null)
  const markerSignature = useMemo(
    () =>
      markers
        .map((marker) => `${marker.id}:${marker.point?.lat ?? 'x'}:${marker.point?.lng ?? 'x'}:${marker.tone}`)
        .join('|'),
    [markers],
  )

  useEffect(() => {
    let cancelled = false
    const markerInstances: any[] = []

    async function renderMap() {
      try {
        await loadGoogleMaps()
        if (cancelled || !mapRef.current) {
          return
        }

        const googleApi = (window as GoogleMapsWindow).google
        if (!googleApi?.maps) {
          throw new Error('Google Maps did not initialize correctly.')
        }

        const map = new googleApi.maps.Map(mapRef.current, {
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          backgroundColor: '#020617',
          styles: [
            { elementType: 'geometry', stylers: [{ color: '#0f172a' }] },
            { elementType: 'labels.text.fill', stylers: [{ color: '#cbd5e1' }] },
            { elementType: 'labels.text.stroke', stylers: [{ color: '#0f172a' }] },
            { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#1e293b' }] },
            { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0f3d5d' }] },
          ],
        })

        const bounds = new googleApi.maps.LatLngBounds()
        const infoWindow = new googleApi.maps.InfoWindow()

        markers.forEach((marker) => {
          if (!marker.point) {
            return
          }
          const instance = new googleApi.maps.Marker({
            map,
            position: { lat: marker.point.lat, lng: marker.point.lng },
            title: marker.label,
            icon: {
              path: googleApi.maps.SymbolPath.CIRCLE,
              fillColor: toneColors[marker.tone],
              fillOpacity: 1,
              strokeColor: '#f8fafc',
              strokeWeight: 1.5,
              scale: 7,
            },
          })
          instance.addListener('click', () => {
            infoWindow.setContent(
              `<div style="padding:8px 10px;max-width:220px;">
                <div style="font-weight:600;color:#0f172a;">${marker.label}</div>
                <div style="margin-top:4px;color:#334155;font-size:12px;line-height:1.5;">${marker.subtitle ?? ''}</div>
              </div>`,
            )
            infoWindow.open({ map, anchor: instance })
          })
          markerInstances.push(instance)
          bounds.extend(instance.getPosition())
        })

        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, 48)
        }
        onError(null)
      } catch (error) {
        onError(error instanceof Error ? error.message : 'Google Maps could not be loaded.')
      }
    }

    void renderMap()

    return () => {
      cancelled = true
      markerInstances.forEach((instance) => instance.setMap(null))
    }
  }, [markerSignature, markers, onError])

  return <div ref={mapRef} className="mt-4 min-h-[390px] overflow-hidden rounded-[1.25rem] border border-white/8" />
}

function FallbackMapSurface({ markers }: { markers: Marker[] }) {
  const lats = markers.map((item) => item.point!.lat)
  const lngs = markers.map((item) => item.point!.lng)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const minLng = Math.min(...lngs)
  const maxLng = Math.max(...lngs)
  const latSpan = Math.max(maxLat - minLat, 0.1)
  const lngSpan = Math.max(maxLng - minLng, 0.1)

  return (
    <div className="mt-4 overflow-hidden rounded-[1.25rem] border border-white/8 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.14),_transparent_35%),linear-gradient(180deg,rgba(15,23,42,0.72),rgba(2,6,23,0.92))]">
      <div className="relative min-h-[390px] bg-[linear-gradient(rgba(148,163,184,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.06)_1px,transparent_1px)] bg-[size:56px_56px]">
        <div className="absolute inset-x-0 top-0 flex items-center justify-between px-4 py-3 text-[11px] uppercase tracking-[0.18em] text-slate-500">
          <span>North</span>
          <span>Fallback tactical surface</span>
        </div>
        {markers.map((marker) => {
          const x = (((marker.point!.lng - minLng) / lngSpan) * 82) + 8
          const y = (((maxLat - marker.point!.lat) / latSpan) * 72) + 12
          return (
            <div
              key={marker.id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${x}%`, top: `${y}%` }}
            >
              <div className={`h-3.5 w-3.5 rounded-full ring-4 ${toneStyles[marker.tone]}`} />
              <div className="mt-2 min-w-36 rounded-xl border border-white/10 bg-black/75 px-3 py-2 shadow-[0_10px_30px_rgba(0,0,0,0.28)] backdrop-blur">
                <p className="text-xs font-semibold text-stone-100">{marker.label}</p>
                {marker.subtitle ? <p className="mt-1 text-[11px] leading-5 text-slate-400">{marker.subtitle}</p> : null}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function LegendRow() {
  return (
    <div className="mt-4 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
      <Legend tone="incident" label="Incidents" />
      <Legend tone="team" label="Teams" />
      <Legend tone="resource" label="Resources" />
      <Legend tone="dispatch" label="Dispatches" />
    </div>
  )
}

function Legend({ tone, label }: { tone: Marker['tone']; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${toneStyles[tone].split(' ')[0]}`} />
      {label}
    </span>
  )
}
