import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { LoginPanel } from '@/components/auth/login-panel'

const push = vi.fn()
const loginDemo = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('@/components/providers/auth-provider', () => ({
  useAuth: () => ({
    loginDemo,
    loginGoogle: vi.fn(),
  }),
}))

describe('LoginPanel', () => {
  it('allows demo entry when the button is pressed', () => {
    render(<LoginPanel />)

    fireEvent.click(screen.getByText('Use seeded demo access'))

    expect(loginDemo).toHaveBeenCalled()
  })
})
