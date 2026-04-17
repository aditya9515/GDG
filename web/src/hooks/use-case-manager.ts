'use client'

import { useState } from 'react'

import { createIncident, deleteIncident, updateIncidentLocation, type SessionState } from '@/lib/api'

export type CaseCreatePayload = {
  rawInput: string
  locationText: string
  lat: string
  lng: string
}

type UseCaseManagerOptions = {
  session: SessionState | null
  onMessage: (message: string | null) => void
  onRefresh: () => Promise<void>
  onDeleted?: (caseId: string) => void
}

export function useCaseManager({ session, onMessage, onRefresh, onDeleted }: UseCaseManagerOptions) {
  const [creatingCase, setCreatingCase] = useState(false)
  const [removingCaseId, setRemovingCaseId] = useState<string | null>(null)

  async function createCaseFromInput(payload: CaseCreatePayload): Promise<boolean> {
    if (!session) {
      return false
    }

    const rawInput = payload.rawInput.trim()
    const locationText = payload.locationText.trim()
    const latText = payload.lat.trim()
    const lngText = payload.lng.trim()
    const hasAnyCoordinate = latText.length > 0 || lngText.length > 0

    if (rawInput.length < 3) {
      onMessage('Add at least a short incident report before creating a case.')
      return false
    }
    if (hasAnyCoordinate && (!latText || !lngText)) {
      onMessage('Provide both latitude and longitude, or leave both blank.')
      return false
    }

    const parsedLat = hasAnyCoordinate ? Number(latText) : null
    const parsedLng = hasAnyCoordinate ? Number(lngText) : null
    if (
      hasAnyCoordinate &&
      (parsedLat === null ||
        parsedLng === null ||
        !Number.isFinite(parsedLat) ||
        !Number.isFinite(parsedLng) ||
        parsedLat < -90 ||
        parsedLat > 90 ||
        parsedLng < -180 ||
        parsedLng > 180)
    ) {
      onMessage('Coordinates must be valid numbers: latitude -90 to 90, longitude -180 to 180.')
      return false
    }

    setCreatingCase(true)
    onMessage(null)
    try {
      const created = await createIncident(rawInput, session)
      const shouldAttachLocation = Boolean(locationText || hasAnyCoordinate)
      if (shouldAttachLocation) {
        try {
          await updateIncidentLocation(
            created.case_id,
            {
              location_text: locationText || 'Manual map pin',
              lat: parsedLat,
              lng: parsedLng,
              location_confidence: hasAnyCoordinate ? 'EXACT' : 'APPROXIMATE',
            },
            session,
          )
          onMessage(`${created.case_id} created and mapped.`)
        } catch (error) {
          onMessage(
            `${created.case_id} was created, but the location update failed: ${
              error instanceof Error ? error.message : 'unknown location error'
            }`,
          )
        }
      } else {
        onMessage(`${created.case_id} created. Add a location when you are ready to map it.`)
      }
      await onRefresh()
      return true
    } catch (error) {
      onMessage(error instanceof Error ? error.message : 'Could not create incident.')
      return false
    } finally {
      setCreatingCase(false)
    }
  }

  async function removeCase(caseId: string): Promise<boolean> {
    if (!session) {
      return false
    }
    const ok = window.confirm(`Remove ${caseId}? This deletes the incident and its linked tokens, evidence metadata, duplicates, and dispatch records.`)
    if (!ok) {
      return false
    }

    setRemovingCaseId(caseId)
    onMessage(null)
    try {
      await deleteIncident(caseId, session)
      onDeleted?.(caseId)
      onMessage(`${caseId} removed.`)
      await onRefresh()
      return true
    } catch (error) {
      onMessage(error instanceof Error ? error.message : 'Could not remove incident.')
      return false
    } finally {
      setRemovingCaseId(null)
    }
  }

  return {
    createCaseFromInput,
    creatingCase,
    removeCase,
    removingCaseId,
  }
}
