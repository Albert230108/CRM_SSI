import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SessionExpiredModal from '../SessionExpiredModal'
import { useAuthStore } from '../../store/authStore'

describe('SessionExpiredModal', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false, sessionExpired: false })
  })

  it('renders nothing when the session has not expired', () => {
    render(<SessionExpiredModal />)
    expect(screen.queryByText(/your session has expired/i)).not.toBeInTheDocument()
  })

  it('prompts to log in again when the session expires, and logs out on confirm', () => {
    useAuthStore.setState({ token: 'abc', isAuthenticated: true, sessionExpired: true })
    render(<SessionExpiredModal />)

    expect(screen.getByText(/your session has expired/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /sign in again/i }))

    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useAuthStore.getState().sessionExpired).toBe(false)
  })
})
