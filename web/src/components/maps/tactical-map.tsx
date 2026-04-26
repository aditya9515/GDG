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
  gm_authFailure?: () => void
}

const toneColors: Record<Marker['tone'], string> = {
  incident: '#dc2626',
  team: '#2563eb',
  resource: '#059669',
  dispatch: '#f97316',
}

const toneRings: Record<Marker['tone'], string> = {
  incident: 'rgba(220, 38, 38, 0.28)',
  team: 'rgba(37, 99, 235, 0.28)',
  resource: 'rgba(5, 150, 105, 0.28)',
  dispatch: 'rgba(249, 115, 22, 0.28)',
}

let googleMapsLoader: Promise<void> | null = null

const googleMapsAuthError =
  'Google Maps rejected the browser key. Enable Maps JavaScript API for NEXT_PUBLIC_GOOGLE_MAPS_API_KEY, then restart the web dev server.'

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
        <div className="mt-4 flex min-h-[260px] items-center justify-center rounded-[1.25rem] border border-dashed border-white/10 bg-black/20 px-5 text-center text-sm leading-6 text-slate-500 sm:min-h-[360px] sm:px-8">
          {emptyMessage}
        </div>
      </MapShell>
    )
  }

  if (ENABLE_GOOGLE_MAPS_UI && !mapError) {
    return (
      <MapShell title={title} count={points.length}>
        <GoogleMapSurface markers={points} onError={setMapError} />
        <LegendRow />
      </MapShell>
    )
  }

  return (
    <MapShell title={title} count={points.length}>
      <FallbackMapSurface markers={points} />
      <LegendRow />
      {mapError ? (
        <p className="mt-3 text-xs text-foreground">
          Google Maps is unavailable, so the local tactical map is shown instead: {mapError}
        </p>
      ) : null}
    </MapShell>
  )
}

function MapShell({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div className="surface-card p-3 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
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
    let authFailed = false
    const markerInstances: any[] = []
    let authFailureTimer: number | null = null
    const typedWindow = window as GoogleMapsWindow
    const previousAuthFailure = typedWindow.gm_authFailure
    const handleAuthFailure = () => {
      previousAuthFailure?.()
      authFailed = true
      googleMapsLoader = null
      if (!cancelled) {
        onError(googleMapsAuthError)
      }
    }
    typedWindow.gm_authFailure = handleAuthFailure

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
          backgroundColor: '#dbeafe',
          styles: [
            { elementType: 'geometry', stylers: [{ color: '#eef7ee' }] },
            { elementType: 'labels.text.fill', stylers: [{ color: '#334155' }] },
            { elementType: 'labels.text.stroke', stylers: [{ color: '#f8fafc' }] },
            { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#94a3b8' }] },
            { featureType: 'landscape.natural', elementType: 'geometry', stylers: [{ color: '#d9f2d7' }] },
            { featureType: 'poi.park', elementType: 'geometry', stylers: [{ color: '#bfe8c4' }] },
            { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#ffffff' }] },
            { featureType: 'road.arterial', elementType: 'geometry', stylers: [{ color: '#fed7aa' }] },
            { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#fdba74' }] },
            { featureType: 'transit', elementType: 'geometry', stylers: [{ color: '#c4b5fd' }] },
            { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#93c5fd' }] },
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
              strokeColor: '#f5f5f5',
              strokeWeight: 1.5,
              scale: 7,
            },
          })
          instance.addListener('click', () => {
            infoWindow.setContent(
              `<div style="padding:8px 10px;max-width:220px;border-left:4px solid ${toneColors[marker.tone]};">
                <div style="font-weight:600;color:#111111;">${marker.label}</div>
                <div style="margin-top:4px;color:#525252;font-size:12px;line-height:1.5;">${marker.subtitle ?? ''}</div>
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
        authFailureTimer = window.setTimeout(() => {
          if (cancelled || !mapRef.current) {
            return
          }
          const hasGoogleError =
            Boolean(mapRef.current.querySelector('.gm-err-container')) ||
            mapRef.current.textContent?.includes("This page didn't load Google Maps correctly")
          if (hasGoogleError) {
            authFailed = true
            googleMapsLoader = null
            onError(googleMapsAuthError)
          }
        }, 1200)
        if (!authFailed) {
          onError(null)
        }
      } catch (error) {
        onError(error instanceof Error ? error.message : 'Google Maps could not be loaded.')
      }
    }

    void renderMap()

    return () => {
      cancelled = true
      if (typedWindow.gm_authFailure === handleAuthFailure) {
        typedWindow.gm_authFailure = previousAuthFailure
      }
      if (authFailureTimer !== null) {
        window.clearTimeout(authFailureTimer)
      }
      markerInstances.forEach((instance) => instance.setMap(null))
    }
  }, [markerSignature, markers, onError])

  return <div ref={mapRef} className="mt-4 min-h-[280px] overflow-hidden rounded-[1.25rem] border border-white/8 sm:min-h-[390px]" />
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
    <div className="mt-4 overflow-hidden rounded-[1.25rem] border border-white/8 bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.22),_transparent_35%),linear-gradient(180deg,rgba(219,234,254,0.96),rgba(220,252,231,0.92))]">
      <div className="relative min-h-[280px] bg-[linear-gradient(rgba(37,99,235,0.09)_1px,transparent_1px),linear-gradient(90deg,rgba(5,150,105,0.08)_1px,transparent_1px)] bg-[size:56px_56px] sm:min-h-[390px]">
        <div className="absolute inset-x-0 top-0 flex items-center justify-between px-4 py-3 text-[11px] uppercase tracking-[0.18em] text-slate-700">
          <span>North</span>
          <span>Local tactical surface</span>
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
              <div
                className="h-4 w-4 rounded-full border-2 border-white shadow-lg"
                style={{
                  backgroundColor: toneColors[marker.tone],
                  boxShadow: `0 0 0 6px ${toneRings[marker.tone]}, 0 12px 24px rgba(15,23,42,0.28)`,
                }}
              />
              <div className="mt-2 hidden min-w-36 rounded-xl border border-slate-200 bg-white/90 px-3 py-2 shadow-[0_10px_30px_rgba(15,23,42,0.22)] backdrop-blur sm:block">
                <p className="text-xs font-semibold text-slate-950">{marker.label}</p>
                {marker.subtitle ? <p className="mt-1 text-[11px] leading-5 text-slate-600">{marker.subtitle}</p> : null}
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
      <Legend tone="incident" label="Incident" />
      <Legend tone="team" label="Team" />
      <Legend tone="resource" label="Resource" />
      <Legend tone="dispatch" label="Dispatch" />
    </div>
  )
}

function Legend({ tone, label }: { tone: Marker['tone']; label: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5">
      <span
        className="inline-block h-2.5 w-2.5 rounded-full"
        style={{ backgroundColor: toneColors[tone] }}
      />
      {label}
    </span>
  )
}
