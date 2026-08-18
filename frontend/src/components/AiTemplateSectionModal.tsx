import { useEffect, useRef, useState } from 'react'
import type { AiTemplateNote, AiTemplateSection, BrainSectionOption } from '../types/aiReplyTemplate'
import { EMAIL_TEMPLATE_PLACEHOLDERS } from '../types/aiReplyTemplate'
import { NOTE_COLORS } from '../lib/aiTemplateCanvas'

const OVERLAY_CLASS =
  'fixed inset-0 z-[90] flex items-center justify-center bg-gray-900/40 p-4'

/** Inserts `token` at the caret and puts the caret straight after it. */
function insertAtCaret(
  element: HTMLTextAreaElement | null,
  value: string,
  token: string,
  onChange: (next: string) => void,
) {
  if (!element) {
    onChange(value + token)
    return
  }
  const start = element.selectionStart ?? value.length
  const end = element.selectionEnd ?? start
  onChange(value.slice(0, start) + token + value.slice(end))
  requestAnimationFrame(() => {
    element.focus()
    const caret = start + token.length
    element.setSelectionRange(caret, caret)
  })
}

type InsertMenuProps = {
  brainSections: BrainSectionOption[]
  onInsert: (token: string) => void
}

function InsertTokenMenu({ brainSections, onInsert }: InsertMenuProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const handleClickAway = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickAway)
    return () => document.removeEventListener('mousedown', handleClickAway)
  }, [open])

  const choose = (token: string) => {
    onInsert(token)
    setOpen(false)
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100"
      >
        + Insert
      </button>
      {open ? (
        <div className="absolute right-0 z-10 mt-1 max-h-72 w-72 overflow-y-auto rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
          <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-400">Tenant</p>
          {EMAIL_TEMPLATE_PLACEHOLDERS.map((placeholder) => (
            <button
              key={placeholder}
              type="button"
              onClick={() => choose(`{{${placeholder}}}`)}
              className="block w-full rounded px-2 py-1 text-left font-mono text-xs text-gray-700 hover:bg-gray-100"
            >
              {`{{${placeholder}}}`}
            </button>
          ))}
          <p className="mt-1 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-400">Brain</p>
          {brainSections.length === 0 ? (
            <p className="px-2 py-1 text-xs text-gray-400">No brain sections yet.</p>
          ) : (
            brainSections.map((section) => (
              <button
                key={section.id}
                type="button"
                onClick={() => choose(`{{brain:${section.path}}}`)}
                className="block w-full truncate rounded px-2 py-1 text-left text-xs text-gray-700 hover:bg-gray-100"
                title={section.path}
              >
                {section.title} <span className="font-mono text-gray-400">{section.path}</span>
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}

type SectionModalProps = {
  section: AiTemplateSection
  orderIndex: number
  orderTotal: number
  brainSections: BrainSectionOption[]
  contentPlaceholderHint: string
  onChange: (id: string, field: 'label' | 'content', value: string) => void
  onMoveOrder: (id: string, direction: -1 | 1) => void
  onStep: (direction: -1 | 1) => void
  onDuplicate: (id: string) => void
  onRemove: (id: string) => void
  onClose: () => void
}

export function AiTemplateSectionModal({
  section,
  orderIndex,
  orderTotal,
  brainSections,
  contentPlaceholderHint,
  onChange,
  onMoveOrder,
  onStep,
  onDuplicate,
  onRemove,
  onClose,
}: SectionModalProps) {
  const id = section.id as string
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [id])

  return (
    <div
      className={OVERLAY_CLASS}
      role="dialog"
      aria-modal="true"
      aria-label="Edit subprompt"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      // The canvas lives inside the editor's <form>; Enter in the label must not submit it.
      onKeyDown={(event) => {
        if (event.key === 'Enter' && (event.target as HTMLElement).tagName === 'INPUT') event.preventDefault()
      }}
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col gap-3 overflow-y-auto rounded-2xl bg-white p-4 shadow-xl">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-cyan-100 text-xs font-bold text-cyan-800">
            {orderIndex + 1}
          </span>
          <input
            type="text"
            value={section.label}
            onChange={(event) => onChange(id, 'label', event.target.value)}
            placeholder="Label, e.g. Persona"
            className="min-w-0 flex-1 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-500"
          />
          <InsertTokenMenu
            brainSections={brainSections}
            onInsert={(token) => insertAtCaret(textareaRef.current, section.content, token, (next) => onChange(id, 'content', next))}
          />
        </div>

        <textarea
          ref={textareaRef}
          value={section.content}
          onChange={(event) => onChange(id, 'content', event.target.value)}
          placeholder={contentPlaceholderHint}
          rows={18}
          className="w-full resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-500"
        />

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={orderIndex === 0}
            onClick={() => onMoveOrder(id, -1)}
            className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-white"
          >
            &uarr; Move earlier
          </button>
          <button
            type="button"
            disabled={orderIndex === orderTotal - 1}
            onClick={() => onMoveOrder(id, 1)}
            className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-white"
          >
            &darr; Move later
          </button>
          <button
            type="button"
            onClick={() => onDuplicate(id)}
            className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100"
          >
            Duplicate
          </button>
          <button
            type="button"
            onClick={() => onRemove(id)}
            className="rounded-lg border border-rose-200 px-2.5 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50"
          >
            Delete
          </button>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              disabled={orderTotal < 2}
              onClick={() => onStep(-1)}
              className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-white"
              title="Edit previous section"
            >
              &lsaquo; Prev
            </button>
            <button
              type="button"
              disabled={orderTotal < 2}
              onClick={() => onStep(1)}
              className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-white"
              title="Edit next section"
            >
              Next &rsaquo;
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-cyan-700"
            >
              Done
            </button>
          </div>
        </div>
        <p className="text-xs text-gray-500">Esc closes. Changes apply immediately, but still need Save on the template.</p>
      </div>
    </div>
  )
}

type NoteModalProps = {
  note: AiTemplateNote
  onChange: (id: string, field: 'text' | 'color', value: string) => void
  onRemove: (id: string) => void
  onClose: () => void
}

export function AiTemplateNoteModal({ note, onChange, onRemove, onClose }: NoteModalProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [note.id])

  return (
    <div
      className={OVERLAY_CLASS}
      role="dialog"
      aria-modal="true"
      aria-label="Edit note"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="flex w-full max-w-lg flex-col gap-3 rounded-2xl bg-white p-4 shadow-xl">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Post-it note</p>
          <div className="flex items-center gap-1.5">
            {NOTE_COLORS.map((color) => (
              <button
                key={color}
                type="button"
                onClick={() => onChange(note.id, 'color', color)}
                style={{ backgroundColor: color }}
                className={`h-5 w-5 rounded-full border ${
                  (note.color ?? NOTE_COLORS[0]) === color ? 'border-gray-700' : 'border-gray-300'
                }`}
                title="Note colour"
                aria-label={`Use colour ${color}`}
              />
            ))}
          </div>
        </div>

        <textarea
          ref={textareaRef}
          value={note.text}
          onChange={(event) => onChange(note.id, 'text', event.target.value)}
          placeholder="Organizational note (never sent to the AI)"
          rows={8}
          className="w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-500"
          style={{ backgroundColor: note.color ?? NOTE_COLORS[0] }}
        />

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onRemove(note.id)}
            className="rounded-lg border border-rose-200 px-2.5 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-cyan-700"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
