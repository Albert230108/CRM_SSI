import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import RichMessageComposer from '../RichMessageComposer'

describe('RichMessageComposer', () => {
  it('does not rewrite the editor DOM on space input before blur', () => {
    const handleChange = vi.fn()

    render(
      <RichMessageComposer
        channel="whatsapp"
        value={{ body: '', bodyHtml: null, bodyFormat: 'plain' }}
        placeholder="Write your reply..."
        onChange={handleChange}
      />,
    )

    const composer = screen.getByRole('textbox', { name: 'Write your reply...' })
    composer.innerHTML = 'Hello&nbsp;world'

    fireEvent.input(composer)

    expect(composer.innerHTML).toContain('&nbsp;')
    expect(handleChange).toHaveBeenLastCalledWith({
      body: 'Hello world',
      bodyHtml: 'Hello world',
      bodyFormat: 'whatsapp_rich',
    })

    fireEvent.blur(composer)

    expect(composer.innerHTML).toBe('Hello world')
  })
})
