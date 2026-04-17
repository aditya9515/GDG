'use client'

import { API_BASE_URL, ENABLE_STORAGE_UPLOADS } from '@/lib/config'
import { uploadFileToStoragePath } from '@/lib/firebase'
import type {
  AssignmentDecision,
  AuthSessionResponse,
  AiStatusResponse,
  CaseDetailResponse,
  CaseRecord,
  DashboardSummary,
  EvalRunSummary,
  IngestionJob,
  Recommendation,
  ResetOrganizationDataResponse,
  ResourceInventory,
  ResourceNeed,
  Team,
  GraphRun,
  Organization,
  OrgInvite,
  OrgMembership,
  OrgRole,
  UploadRegistrationResponse,
  Volunteer,
} from '@/lib/types'

export interface SessionState {
  uid: string
  email?: string | null
  role: string
  enabled?: boolean
  team_scope?: string[]
  organizations?: Organization[]
  memberships?: OrgMembership[]
  active_org_id?: string | null
  default_org_id?: string | null
  is_host?: boolean
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
      ...(session.active_org_id ? { 'X-Org-Id': session.active_org_id } : {}),
    }
  }
  return {
    Authorization: `Bearer ${session.token ?? ''}`,
    ...(session.active_org_id ? { 'X-Org-Id': session.active_org_id } : {}),
  }
}

function buildBearerHeaders(token: string): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  const fallback = `Request failed with status ${response.status}`
  const text = await response.text()
  if (!text) {
    return fallback
  }

  try {
    const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown }
    if (typeof parsed.detail === 'string') {
      return parsed.detail
    }
    if (typeof parsed.message === 'string') {
      return parsed.message
    }
  } catch {
    return text
  }

  return text || fallback
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

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      cache: 'no-store',
    })
  } catch (error) {
    throw new Error(
      `Cannot reach ReliefOps API at ${API_BASE_URL}. Start the backend with npm run dev:api, verify NEXT_PUBLIC_API_BASE_URL, and restart the web dev server. Original error: ${
        error instanceof Error ? error.message : 'network request failed'
      }`,
    )
  }
  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  return response.json() as Promise<T>
}

async function requestWithHeaders<T>(path: string, headersInit: HeadersInit, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers ?? {})
  Object.entries(headersInit).forEach(([key, value]) => {
    if (value) {
      headers.set(key, value)
    }
  })
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      cache: 'no-store',
    })
  } catch (error) {
    throw new Error(
      `Cannot reach ReliefOps API at ${API_BASE_URL}. Start the backend with npm run dev:api, verify NEXT_PUBLIC_API_BASE_URL, and restart the web dev server. Original error: ${
        error instanceof Error ? error.message : 'network request failed'
      }`,
    )
  }
  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  return response.json() as Promise<T>
}

export async function getMeWithToken(token: string): Promise<AuthSessionResponse> {
  return requestWithHeaders<AuthSessionResponse>('/me', buildBearerHeaders(token))
}

export async function getMe(session: SessionState | null): Promise<AuthSessionResponse> {
  return request<AuthSessionResponse>('/me', {}, session)
}

export async function createOrganization(name: string, session: SessionState | null) {
  return request<{ organization: Organization; membership: OrgMembership }>(
    '/organizations',
    { method: 'POST', body: JSON.stringify({ name }) },
    session,
  )
}

export async function listOrganizations(session: SessionState | null) {
  return request<{ items: Organization[]; memberships: OrgMembership[] }>('/organizations', {}, session)
}

export async function getOrganizationMembers(orgId: string, session: SessionState | null) {
  return request<{ organization: Organization; members: OrgMembership[]; invites: OrgInvite[] }>(
    `/organizations/${orgId}/members`,
    {},
    session,
  )
}

export async function inviteOrgMember(orgId: string, email: string, role: OrgRole, session: SessionState | null) {
  return request<{ invite: OrgInvite; status: string }>(
    `/organizations/${orgId}/invites`,
    { method: 'POST', body: JSON.stringify({ email, role }) },
    session,
  )
}

export async function updateOrgMember(
  orgId: string,
  membershipId: string,
  payload: { role?: OrgRole; status?: string },
  session: SessionState | null,
) {
  return request<{ member: OrgMembership }>(
    `/organizations/${orgId}/members/${membershipId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    session,
  )
}

export async function removeOrgMember(orgId: string, membershipId: string, session: SessionState | null) {
  return request<{ member: OrgMembership; status: string }>(
    `/organizations/${orgId}/members/${membershipId}`,
    { method: 'DELETE' },
    session,
  )
}

export async function resetOrganizationData(orgId: string, session: SessionState | null) {
  return request<ResetOrganizationDataResponse>(
    `/organizations/${orgId}/reset-data`,
    { method: 'POST', body: JSON.stringify({ confirmation: 'RESET_ORG_DATA' }) },
    session,
  )
}

export async function runGraph1(
  payload: { source_kind?: string; text: string; target?: string; operator_prompt?: string | null },
  session: SessionState | null,
) {
  return request<{ run: GraphRun }>(
    '/agent/graph1/run',
    { method: 'POST', body: JSON.stringify(payload) },
    session,
)
}

export async function runGraph1File(
  payload: { kind: string; target: string; file: File; operator_prompt?: string | null },
  session: SessionState | null,
  options: { onProgress?: (message: string) => void } = {},
) {
  options.onProgress?.('Parsing file into cleaned source chunks...')
  const form = new FormData()
  form.append('source_kind', payload.kind)
  form.append('target', payload.target)
  if (payload.operator_prompt) {
    form.append('operator_prompt', payload.operator_prompt)
  }
  form.append('file', payload.file)
  options.onProgress?.('Drafting editable preview with the configured AI provider...')
  return request<{ run: GraphRun }>('/agent/graph1/run-file', { method: 'POST', body: form }, session)
}

export async function editGraph1(runId: string, prompt: string, draftId: string | null, session: SessionState | null) {
  return request<{ run: GraphRun }>(
    `/agent/graph1/run/${runId}/edit`,
    { method: 'POST', body: JSON.stringify({ prompt, draft_id: draftId }) },
    session,
  )
}

export async function confirmGraph1(runId: string, session: SessionState | null) {
  return request<{ run: GraphRun }>(`/agent/graph1/run/${runId}/confirm`, { method: 'POST' }, session)
}

export async function removeGraph1Draft(runId: string, draftId: string, reason: string, session: SessionState | null) {
  return request<{ run: GraphRun }>(
    `/agent/graph1/run/${runId}/remove`,
    { method: 'POST', body: JSON.stringify({ draft_id: draftId, reason }) },
    session,
  )
}

export async function runGraph2(payload: { linked_case_id: string; text?: string }, session: SessionState | null) {
  return request<{ run: GraphRun }>(
    '/agent/graph2/run',
    { method: 'POST', body: JSON.stringify(payload) },
    session,
  )
}

export async function getDashboardSummary(session: SessionState | null): Promise<DashboardSummary> {
  return request<DashboardSummary>('/dashboard/summary', {}, session)
}

export async function getAiStatus(session: SessionState | null): Promise<AiStatusResponse> {
  return request<AiStatusResponse>('/ai/status', {}, session)
}

export async function downloadGraphRunCsv(runId: string, session: SessionState | null): Promise<void> {
  const headers = new Headers(buildHeaders(session))
  const response = await fetch(`${API_BASE_URL}/agent/runs/${runId}/export.csv`, {
    headers,
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(await readErrorMessage(response))
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${runId}.csv`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
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

export async function deleteIncident(caseId: string, session: SessionState | null) {
  return request<{ status: string; deleted_id: string; deleted_type: string; request_id: string }>(
    `/incidents/${caseId}`,
    { method: 'DELETE' },
    session,
  )
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

export async function deleteTeam(teamId: string, session: SessionState | null) {
  return request<{ status: string; deleted_id: string; deleted_type: string; request_id: string }>(
    `/teams/${teamId}`,
    { method: 'DELETE' },
    session,
  )
}

export async function listVolunteers(session: SessionState | null): Promise<Volunteer[]> {
  const payload = await request<{ items: Volunteer[] }>('/volunteers', {}, session)
  return payload.items
}

export async function deleteVolunteer(volunteerId: string, session: SessionState | null) {
  return request<{ status: string; deleted_id: string; deleted_type: string; request_id: string }>(
    `/volunteers/${volunteerId}`,
    { method: 'DELETE' },
    session,
  )
}

export async function listResources(session: SessionState | null): Promise<ResourceInventory[]> {
  const payload = await request<{ items: ResourceInventory[] }>('/resources', {}, session)
  return payload.items
}

export async function deleteResource(resourceId: string, session: SessionState | null) {
  return request<{ status: string; deleted_id: string; deleted_type: string; request_id: string }>(
    `/resources/${resourceId}`,
    { method: 'DELETE' },
    session,
  )
}

export async function listDispatches(session: SessionState | null): Promise<AssignmentDecision[]> {
  const payload = await request<{ items: AssignmentDecision[] }>('/dispatches', {}, session)
  return payload.items
}

export async function deleteDispatch(assignmentId: string, session: SessionState | null) {
  return request<{ status: string; deleted_id: string; deleted_type: string; request_id: string }>(
    `/dispatches/${assignmentId}`,
    { method: 'DELETE' },
    session,
  )
}

export async function registerUpload(
  payload: { filename: string; content_type: string; size_bytes: number; linked_entity_id?: string | null },
  session: SessionState | null,
) {
  return request<UploadRegistrationResponse>(
    '/uploads/register',
    {
      method: 'POST',
      body: JSON.stringify({
        ...payload,
        linked_entity_type: 'INCIDENT',
      }),
    },
    session,
  )
}

export async function createIngestionJob(
  payload: { kind: string; target: string; file: File; linked_case_id?: string | null },
  session: SessionState | null,
  options: { onProgress?: (message: string) => void; forceDirectUpload?: boolean } = {},
): Promise<IngestionJob> {
  const shouldUseStorage =
    session?.mode === 'firebase' && ENABLE_STORAGE_UPLOADS && payload.kind !== 'CSV' && !options.forceDirectUpload

  if (shouldUseStorage) {
    options.onProgress?.('Registering Firebase Storage upload...')
    const registration = await registerUpload(
      {
        filename: payload.file.name,
        content_type: payload.file.type || 'application/octet-stream',
        size_bytes: payload.file.size,
        linked_entity_id: payload.linked_case_id ?? null,
      },
      session,
    )
    options.onProgress?.('Uploading file evidence to Firebase Storage...')
    await uploadFileToStoragePath(payload.file, registration.storage_path)

    options.onProgress?.('Starting backend document processing...')
    const form = new FormData()
    form.append('kind', payload.kind)
    form.append('target', payload.target)
    if (payload.linked_case_id) {
      form.append('linked_case_id', payload.linked_case_id)
    }
    form.append('evidence_id', registration.evidence_item.evidence_id)
    form.append('storage_path', registration.storage_path)
    form.append('filename', payload.file.name)
    form.append('content_type', payload.file.type || 'application/octet-stream')
    const job = await request<IngestionJob>('/ingestion-jobs', { method: 'POST', body: form }, session)
    options.onProgress?.(`Import ${job.status.toLowerCase()}: ${job.success_count} records created.`)
    return job
  }

  options.onProgress?.('Uploading CSV directly to the backend for local processing...')
  const form = new FormData()
  form.append('kind', payload.kind)
  form.append('target', payload.target)
  if (payload.linked_case_id) {
    form.append('linked_case_id', payload.linked_case_id)
  }
  form.append('file', payload.file)
  const job = await request<IngestionJob>('/ingestion-jobs', { method: 'POST', body: form }, session)
  options.onProgress?.(`Import ${job.status.toLowerCase()}: ${job.success_count} records created.`)
  return job
}

export async function listIngestionJobs(session: SessionState | null): Promise<IngestionJob[]> {
  const payload = await request<{ items: IngestionJob[] }>('/ingestion-jobs', {}, session)
  return payload.items
}

export async function deleteIngestionJob(jobId: string, session: SessionState | null) {
  return request<{ status: string; deleted_id: string; deleted_type: string; request_id: string }>(
    `/ingestion-jobs/${jobId}`,
    { method: 'DELETE' },
    session,
  )
}

export async function deleteGraphRun(runId: string, session: SessionState | null) {
  return request<{ status: string; deleted_id: string; deleted_type: string; request_id: string }>(
    `/agent/runs/${runId}`,
    { method: 'DELETE' },
    session,
  )
}

export async function getLatestEval(session: SessionState | null): Promise<EvalRunSummary | null> {
  return request<EvalRunSummary | null>('/eval/latest', {}, session)
}
