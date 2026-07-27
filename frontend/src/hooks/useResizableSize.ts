import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BoxType,
  FloatingBoxSize,
  loadFloatingBoxSize,
  saveFloatingBoxSize,
  getUserKeyForFloatingBoxSize,
} from '../lib/floatingBoxSizePreferences'

export type ResizableBoxConfig = {
  boxType: BoxType
  defaultWidth: number
  defaultHeight: number
  minWidth: number
  minHeight: number
  maxWidth?: number
  maxHeight?: number
  user?: { id?: number | string | null; email?: string | null } | null
}

export function useResizableSize(config: ResizableBoxConfig) {
  const { boxType, defaultWidth, defaultHeight, minWidth, minHeight, maxWidth, maxHeight, user } = config

  const userKey = getUserKeyForFloatingBoxSize(user || null)
  const savedSize = loadFloatingBoxSize(boxType, userKey)

  const [size, setSize] = useState<{ width: number; height: number }>({
    width: savedSize?.width ?? defaultWidth,
    height: savedSize?.height ?? defaultHeight,
  })

  const sizeRef = useRef(size)
  useEffect(() => {
    sizeRef.current = size
  }, [size])

  const resizeStateRef = useRef<{
    startX: number
    startY: number
    originWidth: number
    originHeight: number
  } | null>(null)

  const handlePointerDown = useCallback(
    (event: React.PointerEvent) => {
      event.stopPropagation()

      resizeStateRef.current = {
        startX: event.clientX,
        startY: event.clientY,
        originWidth: size.width,
        originHeight: size.height,
      }

      const handlePointerMove = (moveEvent: PointerEvent) => {
        const resizeState = resizeStateRef.current
        if (!resizeState) return

        const deltaX = moveEvent.clientX - resizeState.startX
        const deltaY = moveEvent.clientY - resizeState.startY

        let newWidth = Math.max(minWidth, resizeState.originWidth + deltaX)
        let newHeight = Math.max(minHeight, resizeState.originHeight + deltaY)

        if (maxWidth !== undefined) {
          newWidth = Math.min(newWidth, maxWidth)
        }
        if (maxHeight !== undefined) {
          newHeight = Math.min(newHeight, maxHeight)
        }

        setSize({ width: newWidth, height: newHeight })
      }

      const handlePointerUp = () => {
        if (resizeStateRef.current) {
          const finalSize: FloatingBoxSize = {
            version: 1,
            width: sizeRef.current.width,
            height: sizeRef.current.height,
          }
          saveFloatingBoxSize(boxType, userKey, finalSize)
        }
        resizeStateRef.current = null
        window.removeEventListener('pointermove', handlePointerMove)
        window.removeEventListener('pointerup', handlePointerUp)
      }

      window.addEventListener('pointermove', handlePointerMove)
      window.addEventListener('pointerup', handlePointerUp)
    },
    [size, minWidth, minHeight, maxWidth, maxHeight, boxType, userKey],
  )

  useEffect(() => {
    if (savedSize && (savedSize.width !== size.width || savedSize.height !== size.height)) {
      setSize({ width: savedSize.width, height: savedSize.height })
    }
  }, [])

  const style = {
    width: `${size.width}px`,
    height: `${size.height}px`,
  }

  return { size, handlePointerDown, style }
}
