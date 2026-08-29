import { memo } from 'react'
import type { WorkingMemoryCard } from '../lib/workingMemoryCanvas'
import { cardRect } from '../lib/workingMemoryCanvas'

export type CanvasPointerHandler = (event: React.PointerEvent, id: string, mode: 'move' | 'resize') => void

const STATUS_STYLE: Record<string, string> = {
  active: 'bg-emerald-50 text-emerald-700',
  pending_approval: 'bg-amber-50 text-amber-700',
  dismissed: 'bg-gray-100 text-gray-500',
}

type Props = {
  card: WorkingMemoryCard
  selected: boolean
  primaryLabel: string
  secondaryLabel: string
  onPointerDown: CanvasPointerHandler
  onDuplicate: (id: string) => void
  onRemove: (id: string) => void
}

function WorkingMemoryCanvasCard({ card, selected, primaryLabel, secondaryLabel, onPointerDown, onDuplicate, onRemove }: Props) {
  const rect = cardRect(card)

  return (
    <div
      data-canvas-item
      data-testid={`working-memory-card-${card.id}`}
      className={`group absolute flex cursor-grab select-none flex-col rounded-lg border bg-white p-2.5 shadow-sm transition-shadow active:cursor-grabbing hover:shadow-md ${
        selected ? 'border-brand-500 ring-2 ring-brand-200' : 'border-gray-300'
      }`}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, touchAction: 'none' }}
      onPointerDown={(event) => onPointerDown(event, card.id, 'move')}
    >
      <div className="flex items-center gap-1.5">
        {card.status ? (
          <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${STATUS_STYLE[card.status] ?? 'bg-gray-100 text-gray-500'}`}>
            {card.status.replace('_', ' ')}
          </span>
        ) : null}
        <p className={`min-w-0 flex-1 truncate text-xs font-semibold ${card.primary.trim() ? 'text-gray-900' : 'text-gray-400'}`}>
          {card.primary.trim() || `Untitled ${primaryLabel.toLowerCase()}`}
        </p>
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <button type="button" onClick={() => onDuplicate(card.id)} className="text-[11px] text-gray-400 hover:text-gray-700" title="Duplicate">
            &#10697;
          </button>
          <button type="button" onClick={() => onRemove(card.id)} className="text-xs text-rose-400 hover:text-rose-700" title="Delete">
            &times;
          </button>
        </div>
      </div>

      <p className="mt-1 text-[10px] font-medium uppercase tracking-wide text-gray-400">{secondaryLabel}</p>
      <div className="mt-0.5 min-h-0 flex-1 overflow-hidden rounded-md border border-gray-100 bg-gray-50/60 px-2 py-1.5">
        <p className={`whitespace-pre-wrap break-words text-[11px] leading-snug ${card.secondary.trim() ? 'text-gray-700' : 'text-gray-400'}`}>
          {card.secondary.trim() || 'Click to edit.'}
        </p>
      </div>

      <div
        data-testid={`working-memory-card-resize-${card.id}`}
        className="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize opacity-0 transition-opacity group-hover:opacity-100"
        style={{ touchAction: 'none' }}
        onPointerDown={(event) => onPointerDown(event, card.id, 'resize')}
        title="Resize"
      >
        <span className="absolute bottom-1 right-1 block h-2 w-2 border-b-2 border-r-2 border-gray-400" />
      </div>
    </div>
  )
}

export default memo(WorkingMemoryCanvasCard)
