import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import SyncProgressOverlay from '../SyncProgressOverlay'

const STUCK_AFTER_MS = 5 * 60 * 1000

describe('SyncProgressOverlay', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('offers Stop waiting after five minutes while the sync is still active', () => {
    const onDismiss = vi.fn()

    render(
      <SyncProgressOverlay
        active
        progress={{ phase: 'email', phase_index: 2, phases_total: 4, current: 1, total: 10 }}
        onDismiss={onDismiss}
      />,
    )

    expect(screen.getByRole('status', { name: /syncing data/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /stop waiting/i })).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(STUCK_AFTER_MS)
    })

    const stopWaitingButton = screen.getByRole('button', { name: /stop waiting/i })
    expect(stopWaitingButton).toBeInTheDocument()

    fireEvent.click(stopWaitingButton)
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })
})
