import { memo } from 'react'
import type { AiTemplateSection } from '../types/aiReplyTemplate'
import { sectionRect } from '../lib/aiTemplateCanvas'

export type CanvasPointerHandler = (
  event: React.PointerEvent,
  kind: 'section' | 'note',
  id: string,
  mode: 'move' | 'resize',
) => void

type Props = {
  section: AiTemplateSection
  orderIndex: number
  orderTotal: number
  selected: boolean
  onPointerDown: CanvasPointerHandler
  onMoveOrder: (id: string, direction: -1 | 1) => void
  onDuplicate: (id: string) => void
  onRemove: (id: string) => void
}

/**
 * A section rendered as a read-only preview tile. All editing happens in the popup, which is what
 * lets the whole card be a drag target and a single click mean "open the editor".
 */
function AiTemplateCanvasCard({
  section,
  orderIndex,
  orderTotal,
  selected,
  onPointerDown,
  onMoveOrder,
  onDuplicate,
  onRemove,
}: Props) {
  const id = section.id as string
  const rect = sectionRect(section)

  return (
    <div
      data-canvas-item
      data-testid={`canvas-section-${id}`}
      className={`group absolute flex cursor-grab select-none flex-col rounded-lg border bg-white p-2.5 shadow-sm transition-shadow active:cursor-grabbing hover:shadow-md ${
        selected ? 'border-brand-500 ring-2 ring-brand-200' : 'border-gray-300'
      }`}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, touchAction: 'none' }}
      onPointerDown={(event) => onPointerDown(event, 'section', id, 'move')}
    >
      <div className="flex items-center gap-1.5">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[11px] font-bold text-brand-800">
          {orderIndex + 1}
        </span>
        <div className="flex shrink-0 flex-col">
          <button
            type="button"
            disabled={orderIndex === 0}
            onClick={() => onMoveOrder(id, -1)}
            className="leading-none text-gray-400 hover:text-gray-700 disabled:text-gray-200 disabled:hover:text-gray-200"
            title="Move earlier in prompt order"
          >
            &uarr;
          </button>
          <button
            type="button"
            disabled={orderIndex === orderTotal - 1}
            onClick={() => onMoveOrder(id, 1)}
            className="leading-none text-gray-400 hover:text-gray-700 disabled:text-gray-200 disabled:hover:text-gray-200"
            title="Move later in prompt order"
          >
            &darr;
          </button>
        </div>
        <p className={`min-w-0 flex-1 truncate text-xs font-semibold ${section.label.trim() ? 'text-gray-900' : 'text-gray-400'}`}>
          {section.label.trim() || 'Untitled section'}
        </p>
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <button
            type="button"
            onClick={() => onDuplicate(id)}
            className="text-[11px] text-gray-400 hover:text-gray-700"
            title="Duplicate section"
          >
            &#10697;
          </button>
          <button
            type="button"
            onClick={() => onRemove(id)}
            className="text-xs text-rose-400 hover:text-rose-700"
            title="Delete section"
          >
            &times;
          </button>
        </div>
      </div>

      <div className="mt-1.5 min-h-0 flex-1 overflow-hidden rounded-md border border-gray-100 bg-gray-50/60 px-2 py-1.5">
        <p className={`whitespace-pre-wrap break-words text-[11px] leading-snug ${section.content.trim() ? 'text-gray-700' : 'text-gray-400'}`}>
          {section.content.trim() || 'Click to write this subprompt.'}
        </p>
      </div>

      <div
        data-testid={`canvas-section-resize-${id}`}
        className="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize opacity-0 transition-opacity group-hover:opacity-100"
        style={{ touchAction: 'none' }}
        onPointerDown={(event) => onPointerDown(event, 'section', id, 'resize')}
        title="Resize"
      >
        <span className="absolute bottom-1 right-1 block h-2 w-2 border-b-2 border-r-2 border-gray-400" />
      </div>
    </div>
  )
}

export default memo(AiTemplateCanvasCard)
