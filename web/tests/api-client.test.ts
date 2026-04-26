import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  confirmGraph1,
  getHealth,
  invalidateOperationalCaches,
  listIncidents,
  listTeams,
  type SessionState,
} from '@/lib/api'

vi.mock('@/lib/firebase', () => ({
  uploadFileToStoragePath: vi.fn(),
}))

const firebaseSession: SessionState = {
  uid: 'firebase-user',
  email: 'operator@example.com',
  role: 'HOST',
  active_org_id: 'org-live',
  token: 'firebase-token',
  mode: 'firebase',
}

const demoSession: SessionState = {
  uid: 'demo-coordinator',
  email: 'demo@reliefops.local',
  role: 'HOST',
  active_org_id: 'org-demo',
  mode: 'demo',
}

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function requestHeaders(callIndex = 0) {
  const init = vi.mocked(fetch).mock.calls[callIndex]?.[1] as RequestInit
  return new Headers(init?.headers)
}

describe('frontend API client integration contract', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    invalidateOperationalCaches('all')
    vi.stubGlobal('fetch', vi.fn())
  })

  it('checks backend health without auth headers', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(await jsonResponse({ status: 'ok' }))

    await expect(getHealth()).resolves.toEqual({ status: 'ok' })

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('http://127.0.0.1:8000/health')
    expect(requestHeaders().get('Authorization')).toBeNull()
    expect(requestHeaders().get('X-Org-Id')).toBeNull()
  })

  it('sends Firebase bearer auth and active organization headers', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(await jsonResponse({ items: [] }))

    await listTeams(firebaseSession, 'rescue')

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('http://127.0.0.1:8000/teams?q=rescue')
    expect(requestHeaders().get('Authorization')).toBe('Bearer firebase-token')
    expect(requestHeaders().get('X-Org-Id')).toBe('org-live')
  })

  it('sends demo headers only in demo mode', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(await jsonResponse({ items: [] }))

    await listTeams(demoSession)

    expect(requestHeaders().get('X-Demo-User')).toBe('demo-coordinator')
    expect(requestHeaders().get('X-Org-Id')).toBe('org-demo')
    expect(requestHeaders().get('Authorization')).toBeNull()
  })

  it('invalidates operational list caches after Graph 1 confirmation', async () => {
    let incidentFetchCount = 0
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input)
      if (url.endsWith('/incidents')) {
        incidentFetchCount += 1
        return jsonResponse({ items: [{ case_id: `CASE-${incidentFetchCount}` }] })
      }
      if (url.endsWith('/agent/graph1/run/run-1/confirm')) {
        return jsonResponse({
          run: {
            run_id: 'run-1',
            org_id: 'org-demo',
            graph_name: 'intake_graph',
            status: 'COMMITTED',
            created_by: 'demo-coordinator',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            source_artifacts: [],
            drafts: [],
            user_questions: [],
            user_answers: {},
            needs_user_input: false,
            next_action: null,
            committed_record_ids: ['CASE-2'],
            error_message: null,
            meta: {},
          },
        })
      }
      return jsonResponse({})
    })

    await expect(listIncidents(demoSession)).resolves.toEqual([{ case_id: 'CASE-1' }])
    await expect(listIncidents(demoSession)).resolves.toEqual([{ case_id: 'CASE-1' }])
    expect(incidentFetchCount).toBe(2)

    await confirmGraph1('run-1', demoSession)
    await expect(listIncidents(demoSession)).resolves.toEqual([{ case_id: 'CASE-3' }])
    expect(incidentFetchCount).toBe(3)
  })
})
