import { memo } from 'react'
import type { AiTemplateNote } from '../types/aiReplyTemplate'
import { NOTE_COLORS, noteRect } from '../lib/aiTemplateCanvas'
import type { CanvasPointerHandler } from './AiTemplateCanvasCard'

type Props = {
  note: AiTemplateNote
  selected: boolean
  onPointerDown: CanvasPointerHandler
  onRemove: (id: string) => void
}

/** Post-it tile. Preview only, same as the section card — the popup does the editing. */
function AiTemplateCanvasNote({ note, selected, onPointerDown, onRemove }: Props) {
  const rect = noteRect(note)

  return (
    <div
      data-canvas-item
      data-testid={`canvas-note-${note.id}`}
      className={`group absolute flex cursor-grab select-none flex-col rounded-md p-2 shadow-md active:cursor-grabbing ${
        selected ? 'ring-2 ring-brand-500' : ''
      }`}
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        backgroundColor: note.color ?? NOTE_COLORS[0],
        touchAction: 'none',
      }}
      onPointerDown={(event) => onPointerDown(event, 'note', note.id, 'move')}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-700/70">Note</span>
        <button
          type="button"
          onClick={() => onRemove(note.id)}
          className="text-xs text-gray-700/70 opacity-0 transition-opacity hover:text-gray-900 group-hover:opacity-100"
          title="Delete note"
        >
          &times;
        </button>
      </div>

      <p className={`mt-1 min-h-0 flex-1 overflow-hidden whitespace-pre-wrap break-words text-[11px] leading-snug ${note.text.trim() ? 'text-gray-900' : 'text-gray-700/50'}`}>
        {note.text.trim() || 'Click to write a note (never sent to the AI).'}
      </p>

      <div
        data-testid={`canvas-note-resize-${note.id}`}
        className="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize opacity-0 transition-opacity group-hover:opacity-100"
        style={{ touchAction: 'none' }}
        onPointerDown={(event) => onPointerDown(event, 'note', note.id, 'resize')}
        title="Resize"
      >
        <span className="absolute bottom-1 right-1 block h-2 w-2 border-b-2 border-r-2 border-gray-700/40" />
      </div>
    </div>
  )
}

export default memo(AiTemplateCanvasNote)
