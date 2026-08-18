import { useCallback, useRef } from 'react'
import type { AiTemplateNote, AiTemplateSection } from '../types/aiReplyTemplate'

const NOTE_COLORS = ['#fef08a', '#bbf7d0', '#bfdbfe', '#fbcfe8', '#fed7aa']
const CARD_WIDTH = 260
const CARD_HEIGHT = 190
const CARD_GAP = 24
const COLUMNS = 3

export function nextSectionPosition(count: number) {
  const column = count % COLUMNS
  const row = Math.floor(count / COLUMNS)
  return { x: column * (CARD_WIDTH + CARD_GAP), y: row * (CARD_HEIGHT + CARD_GAP) }
}

type DragTarget = { type: 'section' | 'note'; id: string }

type Props = {
  sections: AiTemplateSection[]
  notes: AiTemplateNote[]
  onSectionsChange: (sections: AiTemplateSection[]) => void
  onNotesChange: (notes: AiTemplateNote[]) => void
  contentPlaceholderHint: string
}

export default function AiTemplateSectionCanvas({
  sections,
  notes,
  onSectionsChange,
  onNotesChange,
  contentPlaceholderHint,
}: Props) {
  const dragStateRef = useRef<{ target: DragTarget; startX: number; startY: number; originX: number; originY: number } | null>(null)

  const beginDrag = useCallback(
    (target: DragTarget, event: React.PointerEvent, originX: number, originY: number) => {
      if ((event.target as HTMLElement).closest('textarea, input, button')) return
      dragStateRef.current = { target, startX: event.clientX, startY: event.clientY, originX, originY }

      const handleMove = (moveEvent: PointerEvent) => {
        const state = dragStateRef.current
        if (!state) return
        const x = state.originX + (moveEvent.clientX - state.startX)
        const y = state.originY + (moveEvent.clientY - state.startY)
        if (state.target.type === 'section') {
          onSectionsChange(sections.map((section) => (section.id === state.target.id ? { ...section, x, y } : section)))
        } else {
          onNotesChange(notes.map((note) => (note.id === state.target.id ? { ...note, x, y } : note)))
        }
      }

      const handleUp = () => {
        dragStateRef.current = null
        window.removeEventListener('pointermove', handleMove)
        window.removeEventListener('pointerup', handleUp)
      }

      window.addEventListener('pointermove', handleMove)
      window.addEventListener('pointerup', handleUp)
    },
    [sections, notes, onSectionsChange, onNotesChange],
  )

  const addSection = () => {
    const position = nextSectionPosition(sections.length)
    const section: AiTemplateSection = {
      id: crypto.randomUUID(),
      label: '',
      content: '',
      order: sections.length,
      x: position.x,
      y: position.y,
    }
    onSectionsChange([...sections, section])
  }

  const removeSection = (id: string) => {
    onSectionsChange(
      sections
        .filter((section) => section.id !== id)
        .map((section, index) => ({ ...section, order: index })),
    )
  }

  const updateSection = (id: string, field: 'label' | 'content', value: string) => {
    onSectionsChange(sections.map((section) => (section.id === id ? { ...section, [field]: value } : section)))
  }

  const bumpOrder = (id: string, direction: -1 | 1) => {
    const sorted = [...sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    const index = sorted.findIndex((section) => section.id === id)
    const targetIndex = index + direction
    if (index === -1 || targetIndex < 0 || targetIndex >= sorted.length) return
    const [moved] = sorted.splice(index, 1)
    sorted.splice(targetIndex, 0, moved)
    onSectionsChange(sorted.map((section, i) => ({ ...section, order: i })))
  }

  const addNote = () => {
    const note: AiTemplateNote = {
      id: crypto.randomUUID(),
      text: '',
      x: 40 + (notes.length % 4) * 40,
      y: -CARD_GAP - 140 - (Math.floor(notes.length / 4) * 40),
      color: NOTE_COLORS[notes.length % NOTE_COLORS.length],
    }
    onNotesChange([...notes, note])
  }

  const updateNoteText = (id: string, text: string) => {
    onNotesChange(notes.map((note) => (note.id === id ? { ...note, text } : note)))
  }

  const removeNote = (id: string) => {
    onNotesChange(notes.filter((note) => note.id !== id))
  }

  const orderedSections = [...sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  const minY = Math.min(0, ...notes.map((note) => note.y))
  const canvasHeight = Math.max(
    CARD_HEIGHT + 40,
    ...sections.map((section) => (section.y ?? 0) + CARD_HEIGHT + 40 - minY),
    ...notes.map((note) => note.y + 140 + 40 - minY),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">1. Template text (subprompts)</p>
        <div className="flex gap-2">
          <button type="button" onClick={addNote} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100">
            + Add post-it
          </button>
          <button type="button" onClick={addSection} className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100">
            + Add section
          </button>
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Drag cards anywhere to organize; the numbered badge (not position) is the order sent to the AI. Post-it notes are
        for your own organization only and are never sent to the AI.
      </p>

      <div
        className="relative w-full overflow-auto rounded-xl border border-gray-200 bg-[linear-gradient(to_right,#f3f4f6_1px,transparent_1px),linear-gradient(to_bottom,#f3f4f6_1px,transparent_1px)] bg-[size:24px_24px] bg-gray-50"
        style={{ height: Math.min(canvasHeight, 640) }}
      >
        <div className="relative" style={{ height: canvasHeight, transform: `translateY(${-minY}px)` }}>
          {orderedSections.map((section) => (
            <div
              key={section.id}
              className="absolute flex flex-col rounded-lg border border-gray-300 bg-white p-2.5 shadow-sm"
              style={{ left: section.x ?? 0, top: section.y ?? 0, width: CARD_WIDTH, minHeight: CARD_HEIGHT }}
              onPointerDown={(event) => beginDrag({ type: 'section', id: section.id as string }, event, section.x ?? 0, section.y ?? 0)}
            >
              <div className="flex cursor-grab items-center gap-1.5 active:cursor-grabbing">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-cyan-100 text-[11px] font-bold text-cyan-800">
                  {(section.order ?? 0) + 1}
                </span>
                <div className="flex shrink-0 flex-col">
                  <button type="button" onClick={() => bumpOrder(section.id as string, -1)} className="leading-none text-gray-400 hover:text-gray-700" title="Move earlier in prompt order">&uarr;</button>
                  <button type="button" onClick={() => bumpOrder(section.id as string, 1)} className="leading-none text-gray-400 hover:text-gray-700" title="Move later in prompt order">&darr;</button>
                </div>
                <input
                  type="text"
                  value={section.label}
                  onChange={(event) => updateSection(section.id as string, 'label', event.target.value)}
                  placeholder="Label, e.g. Persona"
                  className="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs font-semibold text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-500"
                />
                <button type="button" onClick={() => removeSection(section.id as string)} className="shrink-0 text-xs text-rose-500 hover:text-rose-700">&times;</button>
              </div>
              <textarea
                value={section.content}
                onChange={(event) => updateSection(section.id as string, 'content', event.target.value)}
                placeholder={contentPlaceholderHint}
                className="mt-1.5 w-full flex-1 resize-none rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-500"
              />
            </div>
          ))}

          {notes.map((note) => (
            <div
              key={note.id}
              className="absolute flex flex-col rounded-md p-2 shadow-md"
              style={{ left: note.x, top: note.y, width: 160, minHeight: 140, backgroundColor: note.color ?? NOTE_COLORS[0] }}
              onPointerDown={(event) => beginDrag({ type: 'note', id: note.id }, event, note.x, note.y)}
            >
              <div className="flex cursor-grab items-center justify-between active:cursor-grabbing">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-700/70">Note</span>
                <button type="button" onClick={() => removeNote(note.id)} className="text-xs text-gray-700/70 hover:text-gray-900">&times;</button>
              </div>
              <textarea
                value={note.text}
                onChange={(event) => updateNoteText(note.id, event.target.value)}
                placeholder="Organizational note (not sent to AI)"
                className="mt-1 w-full flex-1 resize-none bg-transparent text-xs text-gray-900 outline-none placeholder:text-gray-700/50"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
