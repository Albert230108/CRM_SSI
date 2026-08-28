import { useEffect, useRef, useState } from 'react'
import { InsertTokenMenu, insertAtCaret, type InsertTokenGroup, type InsertTokenItem } from '../lib/insertToken'
import { DATETIME_PLACEHOLDERS, EMAIL_TEMPLATE_PLACEHOLDERS, type AiTemplateNote, type AiTemplateSection, type BrainSectionOption } from '../types/aiReplyTemplate'
import { NOTE_COLORS } from '../lib/aiTemplateCanvas'

const OVERLAY_CLASS =
  'fixed inset-0 z-[90] flex items-center justify-center bg-gray-900/40 p-4'

function literalTokenItems(placeholders: readonly string[]): InsertTokenItem[] {
  return placeholders.map((placeholder) => ({ label: `{{${placeholder}}}`, value: `{{${placeholder}}}` }))
}

function brainTokenItems(brainSections: BrainSectionOption[]): InsertTokenItem[] {
  return brainSections.map((section) => ({
    label: section.title,
    secondaryLabel: section.path,
    title: section.path,
    value: `{{brain:${section.path}}}`,
  }))
}

function sectionTokenGroups(brainSections: BrainSectionOption[]): InsertTokenGroup[] {
  return [
    { label: 'Tenant', tokens: literalTokenItems(EMAIL_TEMPLATE_PLACEHOLDERS) },
    { label: 'Date & time', tokens: literalTokenItems(DATETIME_PLACEHOLDERS) },
    {
      label: 'Brain',
      tokens: brainTokenItems(brainSections),
      emptyMessage: 'No brain sections yet.',
    },
  ]
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
            groups={sectionTokenGroups(brainSections)}
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
              &lsaquo; Previous
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
