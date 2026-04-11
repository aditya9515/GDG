import { test, expect } from '@playwright/test'

test('demo login reaches the command center and renders seeded queue content', async ({ page }) => {
  await page.route('**/dashboard/summary', async (route) => {
    await route.fulfill({
      json: {
        total_cases: 30,
        open_cases: 30,
        critical_cases: 4,
        assigned_today: 1,
        pending_duplicates: 6,
        median_time_to_assign_minutes: 22,
        average_confidence: 0.72,
        mapped_cases: 12,
        mapped_resources: 8,
        mapped_teams: 6,
        active_dispatches: 1,
      },
    })
  })

  await page.route('**/incidents', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ json: { case_id: 'CASE-NEW01', incident_id: 'CASE-NEW01', status: 'NEW', request_id: 'req-1' } })
      return
    }
    await route.fulfill({
      json: {
        items: [
          {
            case_id: 'DR-001',
            raw_input: 'Flood water rising fast near Shantinagar bridge. 4 people on rooftop incl 1 child. Need rescue boat ASAP.',
            source_channel: 'SEEDED',
            status: 'SCORED',
            extracted_json: null,
            priority_score: 88.4,
            priority_rationale: null,
            urgency: 'CRITICAL',
            location_text: 'Shantinagar bridge',
            geo: { lat: 22.5726, lng: 88.3639 },
            location_confidence: 'EXACT',
            duplicate_status: 'NONE',
            created_at: '2026-04-07T08:00:00Z',
            created_by: 'seed-loader',
            notes: [],
            incident_id: 'DR-001',
            info_token_ids: [],
            evidence_ids: [],
            recommended_dispatches: [],
            final_dispatch_id: null,
            hazard_type: null,
            source_languages: ['en'],
          },
        ],
      },
    })
  })

  await page.route('**/incidents/*/extract', async (route) => {
    await route.fulfill({ json: { case_id: 'CASE-NEW01', extracted: { category: 'RESCUE' }, confidence: 0.9, duplicate_candidates: [], request_id: 'req-2' } })
  })
  await page.route('**/incidents/*/score', async (route) => {
    await route.fulfill({ json: { case_id: 'CASE-NEW01', priority_score: 88.4, urgency: 'CRITICAL', rationale: {}, request_id: 'req-3' } })
  })
  await page.route('**/incidents/*/dispatch-options', async (route) => {
    await route.fulfill({
      json: {
        case_id: 'CASE-NEW01',
        recommendations: [
          {
            team_id: 'TEAM-001',
            volunteer_ids: ['VOL-001'],
            resource_ids: ['RES-001'],
            resource_allocations: [{ resource_type: 'RESCUE_BOAT', quantity: 1, unit: 'unit' }],
            match_score: 0.92,
            eta_minutes: 12,
            route_summary: { provider: 'fallback', distance_km: 5.1, duration_minutes: 12, polyline: null },
            reasons: [],
          },
        ],
        unassigned_reason: null,
        request_id: 'req-4',
      },
    })
  })
  await page.route('**/teams', async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            team_id: 'TEAM-001',
            display_name: 'Asha Rescue Team',
            capability_tags: ['RESCUE'],
            member_ids: ['VOL-001'],
            service_radius_km: 45,
            base_label: 'Shantinagar',
            base_geo: { lat: 22.5726, lng: 88.3639 },
            current_label: 'Shantinagar',
            current_geo: { lat: 22.5726, lng: 88.3639 },
            availability_status: 'AVAILABLE',
            active_dispatches: 0,
            reliability_score: 0.95,
            evidence_ids: [],
            notes: [],
          },
        ],
      },
    })
  })
  await page.route('**/resources', async (route) => {
    await route.fulfill({ json: { items: [] } })
  })
  await page.route('**/dispatches', async (route) => {
    await route.fulfill({ json: { items: [] } })
  })
  await page.route('**/ingestion-jobs', async (route) => {
    await route.fulfill({ json: { items: [] } })
  })

  await page.goto('/login')
  await page.getByText('Use seeded demo access').click()
  await expect(page).toHaveURL(/\/command-center$/)
  await expect(page.getByRole('link', { name: /DR-001/i })).toBeVisible()
})
