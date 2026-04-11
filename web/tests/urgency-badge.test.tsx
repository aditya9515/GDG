import React from 'react'
import { render, screen } from '@testing-library/react'

import { UrgencyBadge } from '@/components/cases/urgency-badge'

describe('UrgencyBadge', () => {
  it('renders the provided urgency label', () => {
    render(<UrgencyBadge urgency="CRITICAL" />)

    expect(screen.getByText('CRITICAL')).toBeInTheDocument()
  })
})
