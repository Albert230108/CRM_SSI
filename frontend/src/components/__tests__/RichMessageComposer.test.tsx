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

  it('keeps style-based formatting when the editor is normalized on blur', () => {
    // Reproduces the reported bug: dragging/resizing the dialog blurs the editor, which rewrites
    // the DOM from the sanitized value. Style-based bold from execCommand must survive as a
    // semantic tag rather than collapsing to raw text.
    render(
      <RichMessageComposer
        channel="email"
        value={{ body: '', bodyHtml: null, bodyFormat: 'plain' }}
        placeholder="Write your reply..."
        onChange={vi.fn()}
      />,
    )

    const composer = screen.getByRole('textbox', { name: 'Write your reply...' })
    composer.innerHTML = '<span style="font-weight:bold">hi</span>'

    fireEvent.blur(composer)

    expect(composer.innerHTML).toContain('<strong>hi</strong>')
    expect(composer.innerHTML).not.toContain('style=')
  })

  it('applies list styling utilities to the editor surface', () => {
    render(
      <RichMessageComposer
        channel="email"
        value={{ body: '', bodyHtml: null, bodyFormat: 'plain' }}
        placeholder="Write your reply..."
        onChange={vi.fn()}
      />,
    )

    const composer = screen.getByRole('textbox', { name: 'Write your reply...' })

    expect(composer.className).toContain('[&_ul]:list-disc')
    expect(composer.className).toContain('[&_ol]:list-decimal')
    expect(composer.className).toContain('[&_ul]:pl-5')
    expect(composer.className).toContain('[&_ol]:pl-5')
  })
})
