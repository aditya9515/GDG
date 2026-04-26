import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BatchDispatchPlanner } from '@/components/dispatch/batch-dispatch-planner'
import { Graph2Panel } from '@/components/dispatch/graph2-panel'

const apiMocks = vi.hoisted(() => ({
  confirmGraph2: vi.fn(),
  confirmGraph2Batch: vi.fn(),
  confirmGraph2BatchCase: vi.fn(),
  downloadGraphRunCsv: vi.fn(),
  editGraph2: vi.fn(),
  editGraph2BatchCase: vi.fn(),
  replanGraph2Batch: vi.fn(),
  resumeGraph2: vi.fn(),
  runGraph2: vi.fn(),
  runGraph2Batch: vi.fn(),
}))

vi.mock('@/components/providers/auth-provider', () => ({
  useAuth: () => ({
    user: {
      uid: 'demo-coordinator',
      email: 'demo@reliefops.local',
      active_org_id: 'org-demo',
      role: 'INCIDENT_COORDINATOR',
    },
  }),
}))

vi.mock('@/lib/api', () => apiMocks)

const incident = {
  case_id: 'CASE-BATCH-1',
  incident_id: 'CASE-BATCH-1',
  org_id: 'org-demo',
  raw_input: 'Critical rooftop rescue near the bridge.',
  status: 'SCORED',
  urgency: 'CRITICAL',
  location_text: 'Bridge Road',
  location_confidence: 'EXACT',
  geo: { lat: 25.59, lng: 85.13 },
  priority_score: 91,
}

const recommendation = {
  recommendation_id: 'rec-1',
  team_id: 'TEAM-1',
  volunteer_ids: ['VOL-1'],
  resource_ids: ['RES-1'],
  resource_allocations: [{ resource_type: 'RESCUE_BOAT', quantity: 1 }],
  match_score: 0.92,
  eta_minutes: 12,
  route_summary: {
    provider: 'fallback',
    status: 'fallback',
    distance_km: 5,
    duration_minutes: 12,
  },
  reasons: [],
}

const batchRun = {
  run_id: 'run-batch',
  org_id: 'org-demo',
  graph_name: 'batch_dispatch_planning_graph',
  status: 'WAITING_FOR_CONFIRMATION',
  created_by: 'demo-coordinator',
  source_artifacts: [],
  drafts: [
    {
      draft_id: 'draft-batch',
      draft_type: 'DISPATCH',
      title: 'Global dispatch plan',
      payload: {
        batch_plan: {
          planned_cases: [
            {
              case_id: 'CASE-BATCH-1',
              priority_rank: 1,
              priority_score: 91,
              planning_priority_score: 0.91,
              assignment_status: 'ASSIGNED',
              selected_recommendation: recommendation,
              alternative_recommendations: [recommendation],
              reserve_recommendations: [],
              reasons: ['Highest-priority feasible plan selected.'],
              unmet_requirements: [],
              conflict_flags: [],
            },
          ],
          reserve_pool_team_ids: ['TEAM-RESERVE'],
          reserve_pool_resource_ids: [],
          planning_summary: '1 cases evaluated: 1 assigned.',
          conflicts: [],
          stats: {
            total_cases: 1,
            assigned_count: 1,
            partial_count: 0,
            waiting_count: 0,
            blocked_count: 0,
            unassigned_count: 0,
            reserve_team_count: 1,
            reserve_resource_count: 0,
            conflict_count: 0,
          },
        },
      },
      confidence: 0.9,
      warnings: [],
      display_fields: {},
    },
  ],
  user_questions: [],
  needs_user_input: false,
  next_action: 'confirm_batch_or_edit',
  committed_record_ids: [],
  meta: {},
}

const singleRun = {
  run_id: 'run-single',
  org_id: 'org-demo',
  graph_name: 'dispatch_assignment_graph',
  status: 'WAITING_FOR_CONFIRMATION',
  created_by: 'demo-coordinator',
  source_artifacts: [],
  drafts: [
    {
      draft_id: 'draft-single',
      draft_type: 'DISPATCH',
      title: 'Dispatch plan',
      payload: {
        ranked_recommendations: [recommendation],
        recommendations: [recommendation],
        reserve_teams: [],
        conflicts: [],
        reasoning_summary: 'Nearest capable team selected.',
      },
      confidence: 0.85,
      warnings: [],
      display_fields: {},
    },
  ],
  user_questions: [],
  needs_user_input: false,
  next_action: 'confirm_or_edit',
  committed_record_ids: [],
  meta: {},
}

describe('Batch dispatch planning UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.runGraph2Batch.mockResolvedValue({ run: batchRun })
    apiMocks.replanGraph2Batch.mockResolvedValue({ run: batchRun })
    apiMocks.confirmGraph2Batch.mockResolvedValue({ run: { ...batchRun, status: 'COMMITTED', committed_record_ids: ['asg-1'] } })
    apiMocks.confirmGraph2BatchCase.mockResolvedValue({ run: { ...batchRun, committed_record_ids: ['asg-1'] } })
    apiMocks.runGraph2.mockResolvedValue({ run: singleRun })
    apiMocks.editGraph2.mockResolvedValue({ run: singleRun })
    apiMocks.confirmGraph2.mockResolvedValue({ run: { ...singleRun, status: 'COMMITTED', committed_record_ids: ['asg-1'] } })
  })

  it('runs global planning and keeps selected cards contrast-safe', async () => {
    render(<BatchDispatchPlanner incidents={[incident as any]} />)

    fireEvent.click(screen.getByRole('button', { name: /plan all open cases/i }))

    expect(await screen.findAllByText(/1 cases evaluated/i)).not.toHaveLength(0)
    expect(apiMocks.runGraph2Batch).toHaveBeenCalled()

    const selectedCaseButton = screen
      .getAllByRole('button')
      .find((button) => button.textContent?.includes('CASE-BATCH-1'))
    expect(selectedCaseButton?.className).toContain('light-surface')
    expect(screen.getByRole('button', { name: /confirm full batch/i }).className).toContain('light-surface')
  })

  it('keeps the single-case selected recommendation contrast-safe', async () => {
    render(<Graph2Panel caseId="CASE-BATCH-1" />)

    fireEvent.click(screen.getByRole('button', { name: /create dispatch plan/i }))

    await screen.findByText(/nearest capable team selected/i)
    let selectedRecommendation = screen.getAllByText(/TEAM-1/)[0]?.parentElement
    while (selectedRecommendation && !selectedRecommendation.className.includes('light-surface')) {
      selectedRecommendation = selectedRecommendation.parentElement
    }

    expect(selectedRecommendation?.className).toContain('light-surface')
  })
})
