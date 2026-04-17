import React from 'react'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { AppShell } from '@/components/layout/app-shell'

vi.mock('next/navigation', () => ({
  usePathname: () => '/cases',
}))

vi.mock('@/components/providers/auth-provider', () => ({
  useAuth: () => ({
    user: {
      uid: 'demo-coordinator',
      email: 'demo@reliefops.local',
      role: 'INCIDENT_COORDINATOR',
      active_org_id: 'org-demo',
      organizations: [{ org_id: 'org-demo', name: 'Demo NGO' }],
      is_host: false,
    },
    logout: vi.fn(),
    setActiveOrg: vi.fn(),
  }),
}))

describe('AppShell', () => {
  it('renders a sidebar Cases link', () => {
    render(
      <AppShell>
        <div>Child content</div>
      </AppShell>,
    )

    expect(screen.getByRole('link', { name: /cases/i })).toHaveAttribute('href', '/cases')
  })
})
