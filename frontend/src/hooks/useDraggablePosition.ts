import { useCallback, useRef, useState } from 'react'

export type DraggablePosition = { x: number; y: number }

export function useDraggablePosition() {
  const [position, setPosition] = useState<DraggablePosition>({ x: 0, y: 0 })
  const dragStateRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null)

  const handlePointerDown = useCallback(
    (event: React.PointerEvent) => {
      dragStateRef.current = {
        startX: event.clientX,
        startY: event.clientY,
        originX: position.x,
        originY: position.y,
      }

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const dragState = dragStateRef.current
        if (!dragState) return
        setPosition({
          x: dragState.originX + (moveEvent.clientX - dragState.startX),
          y: dragState.originY + (moveEvent.clientY - dragState.startY),
        })
      }

      const handlePointerUp = () => {
        dragStateRef.current = null
        window.removeEventListener('pointermove', handlePointerMove)
        window.removeEventListener('pointerup', handlePointerUp)
      }

      window.addEventListener('pointermove', handlePointerMove)
      window.addEventListener('pointerup', handlePointerUp)
    },
    [position],
  )

  const style = { transform: `translate(${position.x}px, ${position.y}px)` }

  return { position, handlePointerDown, style }
}
