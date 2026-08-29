import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Modal from '../Modal'

describe('Modal', () => {
  it('renders children only when open', () => {
    const { rerender } = render(
      <Modal open={false} onClose={() => {}}>
        <p>Body</p>
      </Modal>,
    )
    expect(screen.queryByText('Body')).not.toBeInTheDocument()

    rerender(
      <Modal open onClose={() => {}}>
        <p>Body</p>
      </Modal>,
    )
    expect(screen.getByText('Body')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('closes on Escape when dismissable', () => {
    const onClose = vi.fn()
    render(
      <Modal open onClose={onClose}>
        <p>Body</p>
      </Modal>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not close on Escape when not dismissable', () => {
    const onClose = vi.fn()
    render(
      <Modal open onClose={onClose} dismissable={false}>
        <p>Body</p>
      </Modal>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('closes on backdrop click but not on panel click', () => {
    const onClose = vi.fn()
    render(
      <Modal open onClose={onClose} ariaLabel="test dialog">
        <p>Body</p>
      </Modal>,
    )

    // Clicking the panel content should not close.
    fireEvent.click(screen.getByText('Body'))
    expect(onClose).not.toHaveBeenCalled()

    // A press-and-release on the backdrop itself should close.
    const backdrop = screen.getByRole('dialog').parentElement as HTMLElement
    fireEvent.mouseDown(backdrop)
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
