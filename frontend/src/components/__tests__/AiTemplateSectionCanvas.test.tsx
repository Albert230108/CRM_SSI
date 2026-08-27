import { describe, it, expect, beforeAll, beforeEach } from 'vitest'
import { useState } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AiTemplateSectionCanvas from '../AiTemplateSectionCanvas'
import { CARD_HEIGHT, CARD_WIDTH, GRID } from '../../lib/aiTemplateCanvas'
import type { AiTemplateNote, AiTemplateSection } from '../../types/aiReplyTemplate'

function makeSection(overrides: Partial<AiTemplateSection> = {}): AiTemplateSection {
  return {
    id: 'section-a',
    label: 'Persona',
    content: 'You are a friendly host.',
    order: 0,
    x: 0,
    y: 0,
    w: CARD_WIDTH,
    h: CARD_HEIGHT,
    z: 0,
    ...overrides,
  }
}

type Latest = { sections: AiTemplateSection[]; notes: AiTemplateNote[] }

function Harness({
  latest,
  initialSections,
  initialNotes = [],
}: {
  latest: Latest
  initialSections: AiTemplateSection[]
  initialNotes?: AiTemplateNote[]
}) {
  const [sections, setSections] = useState(initialSections)
  const [notes, setNotes] = useState(initialNotes)
  latest.sections = sections
  latest.notes = notes
  return (
    <AiTemplateSectionCanvas
      sections={sections}
      notes={notes}
      onSectionsChange={setSections}
      onNotesChange={setNotes}
      contentPlaceholderHint="Section content"
      brainSections={[{ id: 1, path: 'policies.cancellation', title: 'Cancellation', is_active: true }]}
      viewportKey="test"
    />
  )
}

function setup(initialSections: AiTemplateSection[], initialNotes: AiTemplateNote[] = []) {
  const latest: Latest = { sections: initialSections, notes: initialNotes }
  render(<Harness latest={latest} initialSections={initialSections} initialNotes={initialNotes} />)
  return latest
}

/** jsdom has no PointerEvent, but React and our handlers only read MouseEvent properties. */
function firePointer(
  element: Element,
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  init: { clientX?: number; clientY?: number; altKey?: boolean; button?: number } = {},
) {
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, ...init })
  Object.defineProperty(event, 'pointerId', { value: 1 })
  act(() => {
    element.dispatchEvent(event)
  })
}

function dragBy(
  element: Element,
  delta: { dx: number; dy: number; altKey?: boolean },
  start = { clientX: 100, clientY: 100 },
) {
  firePointer(element, 'pointerdown', start)
  firePointer(element, 'pointermove', {
    clientX: start.clientX + delta.dx,
    clientY: start.clientY + delta.dy,
    altKey: delta.altKey,
  })
  firePointer(element, 'pointerup', {
    clientX: start.clientX + delta.dx,
    clientY: start.clientY + delta.dy,
    altKey: delta.altKey,
  })
}

beforeAll(() => {
  // jsdom implements neither of these; the drag engine relies on pointer capture.
  Element.prototype.setPointerCapture = function setPointerCapture() {}
  Element.prototype.releasePointerCapture = function releasePointerCapture() {}
})

beforeEach(() => {
  window.localStorage.clear()
})

describe('AiTemplateSectionCanvas', () => {
  it('opens the popup editor on a click and leaves the position alone', () => {
    const latest = setup([makeSection()])
    const card = screen.getByTestId('canvas-section-section-a')

    firePointer(card, 'pointerdown', { clientX: 100, clientY: 100 })
    firePointer(card, 'pointerup', { clientX: 100, clientY: 100 })

    expect(screen.getByRole('dialog', { name: 'Edit subprompt' })).toBeInTheDocument()
    expect(screen.getByDisplayValue('You are a friendly host.')).toBeInTheDocument()
    expect(latest.sections[0].x).toBe(0)
    expect(latest.sections[0].y).toBe(0)
  })

  it('treats movement under the threshold as a click, not a drag', () => {
    const latest = setup([makeSection()])
    const card = screen.getByTestId('canvas-section-section-a')

    dragBy(card, { dx: 2, dy: 1 })

    expect(screen.getByRole('dialog', { name: 'Edit subprompt' })).toBeInTheDocument()
    expect(latest.sections[0].x).toBe(0)
    expect(latest.sections[0].y).toBe(0)
  })

  it('drags a card, snaps it to the grid, and does not open the popup', () => {
    const latest = setup([makeSection()])
    const card = screen.getByTestId('canvas-section-section-a')

    dragBy(card, { dx: 100, dy: 60 })

    expect(screen.queryByRole('dialog', { name: 'Edit subprompt' })).not.toBeInTheDocument()
    expect(latest.sections[0].x! % GRID).toBe(0)
    expect(latest.sections[0].y! % GRID).toBe(0)
    expect(latest.sections[0].x).toBe(96)
    expect(latest.sections[0].y).toBe(72)
  })

  it('bypasses snapping while Alt is held', () => {
    const latest = setup([makeSection()])
    const card = screen.getByTestId('canvas-section-section-a')

    dragBy(card, { dx: 100, dy: 60, altKey: true })

    expect(latest.sections[0].x).toBe(100)
    expect(latest.sections[0].y).toBe(60)
  })

  it('aligns a dragged card with a neighbour that is nearly in line', () => {
    const latest = setup([
      makeSection(),
      makeSection({ id: 'section-b', label: 'Message info', order: 1, x: 400, y: 300, z: 1 }),
    ])
    const card = screen.getByTestId('canvas-section-section-b')

    // Two pixels shy of sharing a left edge with section-a: alignment should close the gap.
    dragBy(card, { dx: -398, dy: -40 })

    expect(latest.sections[1].x).toBe(0)
  })

  it('resizes a card in grid steps', () => {
    const latest = setup([makeSection()])
    const handle = screen.getByTestId('canvas-section-resize-section-a')

    dragBy(handle, { dx: 48, dy: 24 })

    expect(latest.sections[0].w).toBe(CARD_WIDTH + 48)
    expect(latest.sections[0].h).toBe(CARD_HEIGHT + 24)
    expect(latest.sections[0].x).toBe(0)
  })

  it('never resizes below the minimum size', () => {
    const latest = setup([makeSection()])
    const handle = screen.getByTestId('canvas-section-resize-section-a')

    dragBy(handle, { dx: -1000, dy: -1000 })

    expect(latest.sections[0].w).toBe(192)
    expect(latest.sections[0].h).toBe(120)
  })

  it('raises the item that was interacted with above everything else', () => {
    const latest = setup(
      [makeSection()],
      [{ id: 'note-a', text: 'Test note', x: 40, y: 40, w: 168, h: 144, z: 5 }],
    )
    const card = screen.getByTestId('canvas-section-section-a')

    firePointer(card, 'pointerdown', { clientX: 100, clientY: 100 })
    firePointer(card, 'pointerup', { clientX: 100, clientY: 100 })

    expect(latest.sections[0].z!).toBeGreaterThan(latest.notes[0].z!)
  })

  it('renumbers prompt order from the card arrows and disables them at the ends', async () => {
    const user = userEvent.setup()
    const latest = setup([
      makeSection(),
      makeSection({ id: 'section-b', label: 'Message info', order: 1, x: 312, y: 0, z: 1 }),
    ])

    const firstCard = screen.getByTestId('canvas-section-section-a')
    expect(firstCard.querySelector('button[title="Move earlier in prompt order"]')).toBeDisabled()

    const secondCard = screen.getByTestId('canvas-section-section-b')
    await user.click(secondCard.querySelector('button[title="Move earlier in prompt order"]')!)

    expect(latest.sections.find((section) => section.id === 'section-b')!.order).toBe(0)
    expect(latest.sections.find((section) => section.id === 'section-a')!.order).toBe(1)
  })

  it('re-lays cards into a clean grid on Tidy up', async () => {
    const user = userEvent.setup()
    const latest = setup([
      makeSection({ x: 517, y: 431 }),
      makeSection({ id: 'section-b', label: 'B', order: 1, x: 13, y: 900, z: 1 }),
    ])

    await user.click(screen.getByRole('button', { name: 'Tidy up' }))

    expect(latest.sections[0]).toMatchObject({ id: 'section-a', x: 0, y: 0 })
    expect(latest.sections[1]).toMatchObject({ id: 'section-b', x: CARD_WIDTH + GRID, y: 0 })
  })

  it('undoes a drag with Ctrl+Z and redoes it with Ctrl+Shift+Z', () => {
    const latest = setup([makeSection()])
    const card = screen.getByTestId('canvas-section-section-a')

    dragBy(card, { dx: 100, dy: 60 })
    expect(latest.sections[0].x).toBe(96)

    act(() => {
      fireEvent.keyDown(window, { key: 'z', ctrlKey: true })
    })
    expect(latest.sections[0].x).toBe(0)
    expect(latest.sections[0].y).toBe(0)

    act(() => {
      fireEvent.keyDown(window, { key: 'z', ctrlKey: true, shiftKey: true })
    })
    expect(latest.sections[0].x).toBe(96)
  })

  it('leaves Ctrl+Z to the browser while the popup textarea has focus', async () => {
    const user = userEvent.setup()
    const latest = setup([makeSection()])
    const card = screen.getByTestId('canvas-section-section-a')

    dragBy(card, { dx: 100, dy: 60 })
    firePointer(card, 'pointerdown', { clientX: 0, clientY: 0 })
    firePointer(card, 'pointerup', { clientX: 0, clientY: 0 })

    const textarea = screen.getByDisplayValue('You are a friendly host.')
    await user.click(textarea)
    act(() => {
      fireEvent.keyDown(textarea, { key: 'z', ctrlKey: true })
    })

    // The canvas undo must not fire: the card stays where the drag left it.
    expect(latest.sections[0].x).toBe(96)
  })

  it('inserts placeholder and brain tokens at the caret from the popup', async () => {
    const user = userEvent.setup()
    const latest = setup([makeSection({ content: '' })])
    const card = screen.getByTestId('canvas-section-section-a')

    firePointer(card, 'pointerdown', { clientX: 0, clientY: 0 })
    firePointer(card, 'pointerup', { clientX: 0, clientY: 0 })

    await user.click(screen.getByRole('button', { name: '+ Insert' }))
    await user.click(screen.getByRole('button', { name: '{{tenant_name}}' }))
    expect(latest.sections[0].content).toBe('{{tenant_name}}')

    await user.click(screen.getByRole('button', { name: '+ Insert' }))
    await user.click(screen.getByRole('button', { name: '{{current_date}}' }))
    expect(latest.sections[0].content).toBe('{{tenant_name}}{{current_date}}')

    await user.click(screen.getByRole('button', { name: '+ Insert' }))
    await user.click(screen.getByRole('button', { name: /policies\.cancellation/ }))
    expect(latest.sections[0].content).toContain('{{brain:policies.cancellation}}')
  })

  it('edits a post-it through its own popup and keeps it off the AI payload wording', async () => {
    const user = userEvent.setup()
    const latest = setup([], [{ id: 'note-a', text: '', x: 0, y: 0, w: 168, h: 144, z: 0 }])
    const note = screen.getByTestId('canvas-note-note-a')

    firePointer(note, 'pointerdown', { clientX: 0, clientY: 0 })
    firePointer(note, 'pointerup', { clientX: 0, clientY: 0 })

    const dialog = screen.getByRole('dialog', { name: 'Edit note' })
    await user.type(dialog.querySelector('textarea')!, 'Remember this')

    expect(latest.notes[0].text).toBe('Remember this')
  })

  it('deletes the selected item with the Delete key', () => {
    const latest = setup([makeSection(), makeSection({ id: 'section-b', order: 1, x: 312, z: 1 })])
    const card = screen.getByTestId('canvas-section-section-b')

    // Dragging selects without opening the popup, so Delete applies to the dragged card.
    dragBy(card, { dx: 48, dy: 48 })
    act(() => {
      fireEvent.keyDown(window, { key: 'Delete' })
    })

    expect(latest.sections).toHaveLength(1)
    expect(latest.sections[0].id).toBe('section-a')
    expect(latest.sections[0].order).toBe(0)
  })
})
