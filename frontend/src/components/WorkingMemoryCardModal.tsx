import { useEffect, useRef } from 'react'
import { InsertTokenMenu, insertAtCaret, type InsertTokenGroup, type InsertTokenItem } from '../lib/insertToken'
import type { WorkingMemoryCard } from '../lib/workingMemoryCanvas'
import { DATETIME_PLACEHOLDERS } from '../types/aiReplyTemplate'

const OVERLAY_CLASS = 'fixed inset-0 z-[90] flex items-center justify-center bg-gray-900/40 p-4'

function literalTokenItems(placeholders: readonly string[]): InsertTokenItem[] {
  return placeholders.map((placeholder) => ({ label: `{{${placeholder}}}`, value: `{{${placeholder}}}` }))
}

function dateTimeTokenGroups(): InsertTokenGroup[] {
  return [{ label: 'Date & time', tokens: literalTokenItems(DATETIME_PLACEHOLDERS) }]
}

type Props = {
  card: WorkingMemoryCard
  primaryLabel: string
  primaryPlaceholder: string
  secondaryLabel: string
  secondaryPlaceholder: string
  showDateTimeTokens?: boolean
  onChange: (id: string, field: 'primary' | 'secondary', value: string) => void
  onDuplicate: (id: string) => void
  onRemove: (id: string) => void
  onClose: () => void
}

export default function WorkingMemoryCardModal({
  card,
  primaryLabel,
  primaryPlaceholder,
  secondaryLabel,
  secondaryPlaceholder,
  showDateTimeTokens = false,
  onChange,
  onDuplicate,
  onRemove,
  onClose,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const dateTimeGroups = dateTimeTokenGroups()

  useEffect(() => {
    textareaRef.current?.focus()
  }, [card.id])

  return (
    <div
      className={OVERLAY_CLASS}
      role="dialog"
      aria-modal="true"
      aria-label={`Edit ${primaryLabel.toLowerCase()}`}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && (event.target as HTMLElement).tagName === 'INPUT') event.preventDefault()
      }}
    >
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col gap-3 overflow-y-auto rounded-2xl bg-white p-4 shadow-xl">
        <div>
          <label className="mb-1 block text-xs font-semibold uppercase tracking-wide text-gray-500">{primaryLabel}</label>
          <input
            type="text"
            value={card.primary}
            onChange={(event) => onChange(card.id, 'primary', event.target.value)}
            placeholder={primaryPlaceholder}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-500"
          />
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between gap-2">
            <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500">{secondaryLabel}</label>
            {showDateTimeTokens ? (
              <InsertTokenMenu
                groups={dateTimeGroups}
                onInsert={(token) =>
                  insertAtCaret(textareaRef.current, card.secondary, token, (next) => onChange(card.id, 'secondary', next))
                }
              />
            ) : null}
          </div>
          <textarea
            ref={textareaRef}
            value={card.secondary}
            onChange={(event) => onChange(card.id, 'secondary', event.target.value)}
            placeholder={secondaryPlaceholder}
            rows={8}
            className="w-full resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm leading-relaxed text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => onDuplicate(card.id)} className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100">
            Duplicate
          </button>
          <button type="button" onClick={() => onRemove(card.id)} className="rounded-lg border border-rose-200 px-2.5 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50">
            Delete
          </button>
          <button type="button" onClick={onClose} className="ml-auto rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-cyan-700">
            Close
          </button>
        </div>
        <p className="text-xs text-gray-500">Esc closes. Changes apply immediately, but still need Save.</p>
      </div>
    </div>
  )
}
