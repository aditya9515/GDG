import type { GeoPoint } from '@/lib/types'

export type ParsedGeoResult =
  | { ok: true; geo: GeoPoint | null }
  | { ok: false; message: string }

export function parseTags(value: string): string[] {
  return value
    .split(/[,;|]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function parseOptionalGeo(latText: string, lngText: string): ParsedGeoResult {
  const lat = latText.trim()
  const lng = lngText.trim()
  const hasAnyCoordinate = lat.length > 0 || lng.length > 0
  if (!hasAnyCoordinate) {
    return { ok: true, geo: null }
  }
  if (!lat || !lng) {
    return { ok: false, message: 'Provide both latitude and longitude, or leave both blank.' }
  }
  const parsedLat = Number(lat)
  const parsedLng = Number(lng)
  if (
    !Number.isFinite(parsedLat) ||
    !Number.isFinite(parsedLng) ||
    parsedLat < -90 ||
    parsedLat > 90 ||
    parsedLng < -180 ||
    parsedLng > 180
  ) {
    return { ok: false, message: 'Coordinates must be valid: latitude -90 to 90, longitude -180 to 180.' }
  }
  return { ok: true, geo: { lat: parsedLat, lng: parsedLng } }
}

