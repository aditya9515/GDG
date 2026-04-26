import type { CaseRecord } from '@/lib/types'

export function humanizeToken(value: unknown): string {
  if (value === null || value === undefined) {
    return 'Not available'
  }

  const raw = String(value).trim()
  if (!raw) {
    return 'Not available'
  }

  return raw
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function compactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '0'
  }
  return new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value)
}

export function incidentSummary(incident: CaseRecord | null | undefined): string {
  if (!incident) {
    return 'No incident summary available.'
  }

  const extracted = (incident.extracted_json ?? {}) as Record<string, unknown>
  const category = typeof extracted.category === 'string' ? humanizeToken(extracted.category) : null
  const location =
    incident.location_text ||
    (typeof extracted.location_text === 'string' ? extracted.location_text : null) ||
    (typeof extracted.location_name === 'string' ? extracted.location_name : null)
  const notes =
    (typeof extracted.notes_for_dispatch === 'string' ? extracted.notes_for_dispatch : null) ||
    (typeof extracted.summary === 'string' ? extracted.summary : null) ||
    (typeof extracted.description === 'string' ? extracted.description : null)
  const source = incident.raw_input?.trim()

  const parts = [category, location, notes].filter((item): item is string => Boolean(item && item.trim()))
  if (parts.length > 0) {
    return parts.join(' - ')
  }

  return source || 'No incident summary available.'
}

export function humanizeList(values: unknown[] | null | undefined): string {
  if (!values?.length) {
    return 'None listed'
  }
  return values.map((value) => humanizeToken(value)).join(', ')
}
