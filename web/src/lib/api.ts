'use client'

import { API_BASE_URL } from '@/lib/config'
import type {
  AssignmentDecision,
  CaseDetailResponse,
  CaseRecord,
  DashboardSummary,
  EvalRunSummary,
  IngestionJob,
  Recommendation,
  ResourceInventory,
  ResourceNeed,
  Team,
  Volunteer,
} from '@/lib/types'

export interface SessionState {
  uid: string
  email?: string | null
  role: string
  token?: string | null
  mode: 'demo' | 'firebase'
}

function buildHeaders(session: SessionState | null): HeadersInit {
  if (!session) {
    return {}
  }
  if (session.mode === 'demo') {
    return {
      'X-Demo-User': session.uid,
    }
  }
  return {
    Authorization: `Bearer ${session.token ?? ''}`,
  }
}

async function request<T>(path: string, init: RequestInit = {}, session: SessionState | null = null): Promise<T> {
  const headers = new Headers(init.headers ?? {})
  const authHeaders = buildHeaders(session)
  Object.entries(authHeaders).forEach(([key, value]) => {
    if (value) {
      headers.set(key, value)
    }
  })
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
    cache: 'no-store',
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed with status ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function getDashboardSummary(session: SessionState | null): Promise<DashboardSummary> {
  return request<DashboardSummary>('/dashboard/summary', {}, session)
}

export async function listIncidents(session: SessionState | null): Promise<CaseRecord[]> {
  const payload = await request<{ items: CaseRecord[] }>('/incidents', {}, session)
  return payload.items
}

export async function listCases(session: SessionState | null): Promise<CaseRecord[]> {
  return listIncidents(session)
}

export async function getIncident(caseId: string, session: SessionState | null): Promise<CaseDetailResponse> {
  return request<CaseDetailResponse>(`/incidents/${caseId}`, {}, session)
}

export async function getCase(caseId: string, session: SessionState | null): Promise<CaseDetailResponse> {
  return getIncident(caseId, session)
}

export async function createIncident(rawInput: string, session: SessionState | null): Promise<{ case_id: string; incident_id?: string | null }> {
  return request<{ case_id: string; incident_id?: string | null }>(
    '/incidents',
    {
      method: 'POST',
      body: JSON.stringify({ raw_input: rawInput, source_channel: 'MANUAL' }),
    },
    session,
  )
}

export async function createCase(rawInput: string, session: SessionState | null) {
  return createIncident(rawInput, session)
}

export async function extractIncident(caseId: string, session: SessionState | null) {
  return request(`/incidents/${caseId}/extract`, { method: 'POST' }, session)
}

export async function extractCase(caseId: string, session: SessionState | null) {
  return extractIncident(caseId, session)
}

export async function scoreIncident(caseId: string, session: SessionState | null) {
  return request(`/incidents/${caseId}/score`, { method: 'POST' }, session)
}

export async function scoreCase(caseId: string, session: SessionState | null) {
  return scoreIncident(caseId, session)
}

export async function getDispatchOptions(
  caseId: string,
  session: SessionState | null,
): Promise<{
  recommendations: Recommendation[]
  unassigned_reason: string | null
}> {
  return request(`/incidents/${caseId}/dispatch-options`, { method: 'POST' }, session)
}

export async function recommendCase(caseId: string, session: SessionState | null) {
  return getDispatchOptions(caseId, session)
}

export async function updateIncidentLocation(
  caseId: string,
  payload: { location_text: string; lat?: number | null; lng?: number | null; location_confidence: string },
  session: SessionState | null,
) {
  return request<CaseDetailResponse>(
    `/incidents/${caseId}/location`,
    { method: 'POST', body: JSON.stringify(payload) },
    session,
  )
}

export async function dispatchIncident(
  caseId: string,
  payload: {
    team_id?: string | null
    volunteer_ids: string[]
    resource_ids?: string[]
    resource_allocations: ResourceNeed[]
  },
  session: SessionState | null,
) {
  return request(`/incidents/${caseId}/dispatch`, { method: 'POST', body: JSON.stringify(payload) }, session)
}

export async function assignCase(
  caseId: string,
  volunteerIds: string[],
  resourceAllocations: ResourceNeed[],
  session: SessionState | null,
  teamId?: string | null,
  resourceIds?: string[],
) {
  return dispatchIncident(
    caseId,
    {
      team_id: teamId,
      volunteer_ids: volunteerIds,
      resource_ids: resourceIds ?? [],
      resource_allocations: resourceAllocations,
    },
    session,
  )
}

export async function listTeams(session: SessionState | null): Promise<Team[]> {
  const payload = await request<{ items: Team[] }>('/teams', {}, session)
  return payload.items
}

export async function listVolunteers(session: SessionState | null): Promise<Volunteer[]> {
  const payload = await request<{ items: Volunteer[] }>('/volunteers', {}, session)
  return payload.items
}

export async function listResources(session: SessionState | null): Promise<ResourceInventory[]> {
  const payload = await request<{ items: ResourceInventory[] }>('/resources', {}, session)
  return payload.items
}

export async function listDispatches(session: SessionState | null): Promise<AssignmentDecision[]> {
  const payload = await request<{ items: AssignmentDecision[] }>('/dispatches', {}, session)
  return payload.items
}

export async function registerUpload(
  payload: { filename: string; content_type: string; size_bytes: number; linked_entity_id?: string | null },
  session: SessionState | null,
) {
  return request('/uploads/register', { method: 'POST', body: JSON.stringify(payload) }, session)
}

export async function createIngestionJob(
  payload: { kind: string; target: string; file: File; linked_case_id?: string | null },
  session: SessionState | null,
): Promise<IngestionJob> {
  const form = new FormData()
  form.append('kind', payload.kind)
  form.append('target', payload.target)
  if (payload.linked_case_id) {
    form.append('linked_case_id', payload.linked_case_id)
  }
  form.append('file', payload.file)
  return request<IngestionJob>('/ingestion-jobs', { method: 'POST', body: form }, session)
}

export async function listIngestionJobs(session: SessionState | null): Promise<IngestionJob[]> {
  const payload = await request<{ items: IngestionJob[] }>('/ingestion-jobs', {}, session)
  return payload.items
}

export async function getLatestEval(session: SessionState | null): Promise<EvalRunSummary | null> {
  return request<EvalRunSummary | null>('/eval/latest', {}, session)
}
