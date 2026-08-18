import { useCallback, useEffect, useRef, useState } from 'react'

export const MIN_ZOOM = 0.4
export const MAX_ZOOM = 2

export type Viewport = { zoom: number; panX: number; panY: number }
export type CanvasBounds = { minX: number; minY: number; maxX: number; maxY: number }

const DEFAULT_VIEWPORT: Viewport = { zoom: 1, panX: 24, panY: 24 }
const FIT_PADDING = 40

export function clampZoom(zoom: number) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom))
}

function storageKey(persistKey: string) {
  return `ai-template-canvas-viewport:${persistKey}`
}

function loadViewport(persistKey: string): Viewport | null {
  try {
    const raw = window.localStorage.getItem(storageKey(persistKey))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Viewport>
    if (typeof parsed?.zoom !== 'number' || typeof parsed?.panX !== 'number' || typeof parsed?.panY !== 'number') {
      return null
    }
    return { zoom: clampZoom(parsed.zoom), panX: parsed.panX, panY: parsed.panY }
  } catch {
    // Corrupt or unavailable storage should never break the editor.
    return null
  }
}

/**
 * Pan/zoom state for a transform-based canvas surface.
 *
 * The surface is rendered as `translate(panX, panY) scale(zoom)` with a `0 0` origin, so canvas
 * coordinates can be negative and the surface needs no explicit size.
 */
export function useCanvasViewport(persistKey: string) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [restored] = useState(() => loadViewport(persistKey))
  const [viewport, setViewport] = useState<Viewport>(() => restored ?? DEFAULT_VIEWPORT)

  // The wheel listener is registered once with { passive: false }, so it needs a live mirror
  // rather than the value captured when it was attached.
  const viewportRef = useRef(viewport)
  viewportRef.current = viewport

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey(persistKey), JSON.stringify(viewport))
    } catch {
      // Storage being full or blocked is not worth surfacing.
    }
  }, [persistKey, viewport])

  /** Keeps the canvas point under (clientX, clientY) pinned while the zoom changes. */
  const zoomAtClient = useCallback((nextZoom: number, clientX: number, clientY: number) => {
    const element = containerRef.current
    if (!element) return
    const rect = element.getBoundingClientRect()
    setViewport((current) => {
      const zoom = clampZoom(nextZoom)
      const screenX = clientX - rect.left
      const screenY = clientY - rect.top
      const canvasX = (screenX - current.panX) / current.zoom
      const canvasY = (screenY - current.panY) / current.zoom
      return { zoom, panX: screenX - canvasX * zoom, panY: screenY - canvasY * zoom }
    })
  }, [])

  const zoomAtCenter = useCallback((nextZoom: number) => {
    const element = containerRef.current
    if (!element) return
    const rect = element.getBoundingClientRect()
    zoomAtClient(nextZoom, rect.left + rect.width / 2, rect.top + rect.height / 2)
  }, [zoomAtClient])

  const zoomBy = useCallback((factor: number) => {
    zoomAtCenter(viewportRef.current.zoom * factor)
  }, [zoomAtCenter])

  const resetZoom = useCallback(() => {
    zoomAtCenter(1)
  }, [zoomAtCenter])

  const panBy = useCallback((dx: number, dy: number) => {
    setViewport((current) => ({ ...current, panX: current.panX + dx, panY: current.panY + dy }))
  }, [])

  /** Centres `bounds` in the viewport at the largest zoom (never above 1) that fits it. */
  const fitTo = useCallback((bounds: CanvasBounds | null) => {
    const element = containerRef.current
    if (!element || !bounds) return
    const width = element.clientWidth
    const height = element.clientHeight
    if (!width || !height) return

    const contentWidth = Math.max(1, bounds.maxX - bounds.minX)
    const contentHeight = Math.max(1, bounds.maxY - bounds.minY)
    const zoom = clampZoom(
      Math.min(1, (width - FIT_PADDING * 2) / contentWidth, (height - FIT_PADDING * 2) / contentHeight),
    )
    setViewport({
      zoom,
      panX: (width - contentWidth * zoom) / 2 - bounds.minX * zoom,
      panY: (height - contentHeight * zoom) / 2 - bounds.minY * zoom,
    })
  }, [])

  /** Screen (client) coordinates to canvas coordinates. */
  const toCanvas = useCallback((clientX: number, clientY: number) => {
    const element = containerRef.current
    const current = viewportRef.current
    if (!element) return { x: 0, y: 0 }
    const rect = element.getBoundingClientRect()
    return {
      x: (clientX - rect.left - current.panX) / current.zoom,
      y: (clientY - rect.top - current.panY) / current.zoom,
    }
  }, [])

  useEffect(() => {
    const element = containerRef.current
    if (!element) return

    const handleWheel = (event: WheelEvent) => {
      event.preventDefault()
      if (event.ctrlKey || event.metaKey) {
        zoomAtClient(viewportRef.current.zoom * Math.exp(-event.deltaY * 0.002), event.clientX, event.clientY)
        return
      }
      const dx = event.shiftKey ? event.deltaY || event.deltaX : event.deltaX
      const dy = event.shiftKey ? 0 : event.deltaY
      setViewport((current) => ({ ...current, panX: current.panX - dx, panY: current.panY - dy }))
    }

    element.addEventListener('wheel', handleWheel, { passive: false })
    return () => element.removeEventListener('wheel', handleWheel)
  }, [zoomAtClient])

  return {
    containerRef,
    viewport,
    viewportRef,
    hasRestoredViewport: restored !== null,
    zoomBy,
    zoomAtCenter,
    resetZoom,
    panBy,
    fitTo,
    toCanvas,
  }
}
