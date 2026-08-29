import { useRef } from 'react'

const KEYBOARD_STEP = 16
const KEYBOARD_STEP_LARGE = 64

type ColumnResizeHandleProps = {
  label: string
  disabled?: boolean
  valueNow: number
  valueMin: number
  valueMax: number
  /** Called once when a drag or keyboard adjustment begins, so callers can snapshot the starting width. */
  onAdjustStart: () => void
  /** Called continuously while dragging/adjusting with the raw pixel delta since onAdjustStart fired. */
  onAdjust: (deltaPx: number) => void
  /** Called once the drag (or a single keyboard adjustment) is complete, so callers can persist the result. */
  onAdjustEnd: () => void
}

export default function ColumnResizeHandle({
  label,
  disabled = false,
  valueNow,
  valueMin,
  valueMax,
  onAdjustStart,
  onAdjust,
  onAdjustEnd,
}: ColumnResizeHandleProps) {
  const dragStartXRef = useRef(0)

  if (disabled) {
    return <div aria-hidden="true" style={{ width: 10, flexShrink: 0 }} />
  }

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 && event.pointerType === 'mouse') return
    dragStartXRef.current = event.clientX
    event.currentTarget.setPointerCapture(event.pointerId)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    onAdjustStart()
  }

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    const deltaPx = event.clientX - dragStartXRef.current
    onAdjust(deltaPx)
  }

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    document.body.style.userSelect = ''
    document.body.style.cursor = ''
    onAdjustEnd()
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? KEYBOARD_STEP_LARGE : KEYBOARD_STEP
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      onAdjustStart()
      onAdjust(step)
      onAdjustEnd()
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault()
      onAdjustStart()
      onAdjust(-step)
      onAdjustEnd()
    }
  }

  return (
    <div
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={Math.round(valueNow)}
      aria-valuemin={Math.round(valueMin)}
      aria-valuemax={Math.round(valueMax)}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onKeyDown={handleKeyDown}
      className="group relative flex shrink-0 items-stretch justify-center outline-none"
      style={{ width: 10, cursor: 'col-resize', touchAction: 'none' }}
    >
      <div className="h-full w-px bg-gray-200 transition-colors group-hover:bg-brand-400 group-focus-visible:bg-brand-500 group-active:bg-brand-500" />
    </div>
  )
}
