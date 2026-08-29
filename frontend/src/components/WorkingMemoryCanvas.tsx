import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MAX_ZOOM, MIN_ZOOM, useCanvasViewport } from '../hooks/useCanvasViewport'
import {
  CARD_HEIGHT,
  CARD_WIDTH,
  GRID,
  MIN_CARD_HEIGHT,
  MIN_CARD_WIDTH,
  cardRect,
  contentBounds,
  maxZ,
  nextCardPosition,
  snapRect,
  snapToGrid,
  tidyLayout,
  type Rect,
  type WorkingMemoryCard,
} from '../lib/workingMemoryCanvas'
import WorkingMemoryCanvasCard from './WorkingMemoryCanvasCard'
import WorkingMemoryCardModal from './WorkingMemoryCardModal'

const DRAG_THRESHOLD = 4
const HISTORY_LIMIT = 50

type DragState = {
  id: string
  mode: 'move' | 'resize'
  pointerId: number
  element: HTMLElement
  startClientX: number
  startClientY: number
  origin: Rect
  next: Rect
  moved: boolean
  snapshot: WorkingMemoryCard[]
  frame: number | null
}

type Props = {
  cards: WorkingMemoryCard[]
  onCardsChange: (cards: WorkingMemoryCard[]) => void
  primaryLabel: string
  primaryPlaceholder: string
  secondaryLabel: string
  secondaryPlaceholder: string
  showDateTimeTokens?: boolean
  addButtonLabel: string
  viewportKey: string
}

export default function WorkingMemoryCanvas({
  cards,
  onCardsChange,
  primaryLabel,
  primaryPlaceholder,
  secondaryLabel,
  secondaryPlaceholder,
  showDateTimeTokens = false,
  addButtonLabel,
  viewportKey,
}: Props) {
  const { containerRef, viewport, viewportRef, hasRestoredViewport, zoomBy, resetZoom, panBy, fitTo, toCanvas } =
    useCanvasViewport(viewportKey)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [historyVersion, setHistoryVersion] = useState(0)

  const cardsRef = useRef(cards)
  cardsRef.current = cards

  const undoRef = useRef<WorkingMemoryCard[][]>([])
  const redoRef = useRef<WorkingMemoryCard[][]>([])
  const dragRef = useRef<DragState | null>(null)
  const panRef = useRef<{ pointerId: number; startX: number; startY: number } | null>(null)
  const vGuideRef = useRef<HTMLDivElement | null>(null)
  const hGuideRef = useRef<HTMLDivElement | null>(null)
  const didInitialFit = useRef(hasRestoredViewport)

  // ---------------------------------------------------------------- history

  const pushHistory = useCallback((previous: WorkingMemoryCard[]) => {
    undoRef.current = [...undoRef.current.slice(-(HISTORY_LIMIT - 1)), previous]
    redoRef.current = []
    setHistoryVersion((current) => current + 1)
  }, [])

  const undo = useCallback(() => {
    const previous = undoRef.current[undoRef.current.length - 1]
    if (!previous) return
    undoRef.current = undoRef.current.slice(0, -1)
    redoRef.current = [...redoRef.current, cardsRef.current]
    onCardsChange(previous)
    setHistoryVersion((current) => current + 1)
  }, [onCardsChange])

  const redo = useCallback(() => {
    const next = redoRef.current[redoRef.current.length - 1]
    if (!next) return
    redoRef.current = redoRef.current.slice(0, -1)
    undoRef.current = [...undoRef.current, cardsRef.current]
    onCardsChange(next)
    setHistoryVersion((current) => current + 1)
  }, [onCardsChange])

  const { canUndo, canRedo } = useMemo(
    () => ({ canUndo: undoRef.current.length > 0, canRedo: redoRef.current.length > 0 }),
    [historyVersion],
  )

  const editBaselineRef = useRef<{ pushed: boolean; snapshot: WorkingMemoryCard[] } | null>(null)
  useEffect(() => {
    editBaselineRef.current = openId ? { pushed: false, snapshot: cardsRef.current } : null
  }, [openId])

  const recordEdit = useCallback(() => {
    const baseline = editBaselineRef.current
    if (!baseline || baseline.pushed) return
    baseline.pushed = true
    pushHistory(baseline.snapshot)
  }, [pushHistory])

  // ---------------------------------------------------------------- mutations

  const addCard = () => {
    pushHistory(cardsRef.current)
    const position = nextCardPosition(cards.length)
    const card: WorkingMemoryCard = {
      id: crypto.randomUUID(),
      serverId: null,
      primary: '',
      secondary: '',
      x: position.x,
      y: position.y,
      w: CARD_WIDTH,
      h: CARD_HEIGHT,
      z: maxZ(cards) + 1,
    }
    onCardsChange([...cards, card])
    setOpenId(card.id)
  }

  const removeCard = useCallback(
    (id: string) => {
      pushHistory(cardsRef.current)
      setOpenId((current) => (current === id ? null : current))
      onCardsChange(cardsRef.current.filter((card) => card.id !== id))
    },
    [onCardsChange, pushHistory],
  )

  const duplicateCard = useCallback(
    (id: string) => {
      const source = cardsRef.current.find((card) => card.id === id)
      if (!source) return
      pushHistory(cardsRef.current)
      const rect = cardRect(source)
      const copy: WorkingMemoryCard = {
        ...source,
        id: crypto.randomUUID(),
        serverId: null,
        x: rect.x + GRID,
        y: rect.y + GRID,
        z: maxZ(cardsRef.current) + 1,
      }
      onCardsChange([...cardsRef.current, copy])
      setOpenId(copy.id)
    },
    [onCardsChange, pushHistory],
  )

  const updateCard = useCallback(
    (id: string, field: 'primary' | 'secondary', value: string) => {
      recordEdit()
      onCardsChange(cardsRef.current.map((card) => (card.id === id ? { ...card, [field]: value } : card)))
    },
    [onCardsChange, recordEdit],
  )

  const tidyUp = () => {
    if (cards.length === 0) return
    pushHistory(cardsRef.current)
    onCardsChange(tidyLayout(cards))
  }

  const bringToFront = useCallback(
    (id: string) => {
      const top = maxZ(cardsRef.current)
      const current = cardsRef.current.find((card) => card.id === id)
      if (!current || current.z === top) return
      onCardsChange(cardsRef.current.map((card) => (card.id === id ? { ...card, z: top + 1 } : card)))
    },
    [onCardsChange],
  )

  // ---------------------------------------------------------------- alignment guides

  const showGuides = useCallback(
    (guideX: number | null, guideY: number | null) => {
      const zoom = viewportRef.current.zoom
      const vertical = vGuideRef.current
      const horizontal = hGuideRef.current
      if (vertical) {
        vertical.style.display = guideX === null ? 'none' : 'block'
        if (guideX !== null) {
          vertical.style.left = `${guideX}px`
          vertical.style.width = `${1 / zoom}px`
        }
      }
      if (horizontal) {
        horizontal.style.display = guideY === null ? 'none' : 'block'
        if (guideY !== null) {
          horizontal.style.top = `${guideY}px`
          horizontal.style.height = `${1 / zoom}px`
        }
      }
    },
    [viewportRef],
  )

  const hideGuides = useCallback(() => showGuides(null, null), [showGuides])

  // ---------------------------------------------------------------- drag engine

  const paintDrag = useCallback(() => {
    const drag = dragRef.current
    if (!drag) return
    drag.frame = null
    drag.element.style.left = `${drag.next.x}px`
    drag.element.style.top = `${drag.next.y}px`
    drag.element.style.width = `${drag.next.w}px`
    drag.element.style.height = `${drag.next.h}px`
  }, [])

  const handleDragMove = useCallback(
    (event: PointerEvent) => {
      const drag = dragRef.current
      if (!drag || event.pointerId !== drag.pointerId) return

      const rawDx = event.clientX - drag.startClientX
      const rawDy = event.clientY - drag.startClientY
      if (!drag.moved && Math.hypot(rawDx, rawDy) < DRAG_THRESHOLD) return
      drag.moved = true

      const zoom = viewportRef.current.zoom
      const dx = rawDx / zoom
      const dy = rawDy / zoom
      const free = event.altKey

      if (drag.mode === 'move') {
        const candidate: Rect = { ...drag.origin, x: drag.origin.x + dx, y: drag.origin.y + dy }
        if (free) {
          drag.next = candidate
          hideGuides()
        } else {
          const others: Rect[] = cardsRef.current.filter((card) => card.id !== drag.id).map(cardRect)
          const snapped = snapRect(candidate, others)
          drag.next = { ...candidate, x: snapped.x, y: snapped.y }
          showGuides(snapped.guideX, snapped.guideY)
        }
      } else {
        let w = drag.origin.w + dx
        let h = drag.origin.h + dy
        if (!free) {
          w = snapToGrid(w)
          h = snapToGrid(h)
        }
        drag.next = { ...drag.origin, w: Math.max(MIN_CARD_WIDTH, w), h: Math.max(MIN_CARD_HEIGHT, h) }
      }

      if (drag.frame === null) drag.frame = requestAnimationFrame(paintDrag)
    },
    [hideGuides, paintDrag, showGuides, viewportRef],
  )

  const endDrag = useCallback(() => {
    const drag = dragRef.current
    if (!drag) return
    dragRef.current = null
    if (drag.frame !== null) cancelAnimationFrame(drag.frame)
    hideGuides()
    drag.element.style.zIndex = ''
    try {
      drag.element.releasePointerCapture(drag.pointerId)
    } catch {
      // Capture is already released when the pointer left the window.
    }

    if (!drag.moved) {
      bringToFront(drag.id)
      setOpenId(drag.id)
      return
    }

    pushHistory(drag.snapshot)
    const top = maxZ(cardsRef.current)
    onCardsChange(
      cardsRef.current.map((card) =>
        card.id === drag.id
          ? { ...card, x: drag.next.x, y: drag.next.y, w: drag.next.w, h: drag.next.h, z: card.z === top ? card.z : top + 1 }
          : card,
      ),
    )
  }, [bringToFront, hideGuides, onCardsChange, pushHistory])

  const handleDragMoveRef = useRef(handleDragMove)
  handleDragMoveRef.current = handleDragMove
  const endDragRef = useRef(endDrag)
  endDragRef.current = endDrag

  const handleItemPointerDown = useCallback((event: React.PointerEvent, id: string, mode: 'move' | 'resize') => {
    if (event.button !== 0) return
    if (mode === 'move' && (event.target as HTMLElement).closest('button')) return

    const element = (event.target as HTMLElement).closest('[data-canvas-item]') as HTMLElement | null
    if (!element) return

    const source = cardsRef.current.find((card) => card.id === id)
    if (!source) return
    const origin = cardRect(source)

    event.stopPropagation()
    setSelectedId(id)
    element.setPointerCapture(event.pointerId)
    element.style.zIndex = '60'

    dragRef.current = {
      id,
      mode,
      pointerId: event.pointerId,
      element,
      startClientX: event.clientX,
      startClientY: event.clientY,
      origin,
      next: origin,
      moved: false,
      snapshot: cardsRef.current,
      frame: null,
    }

    const onMove = (moveEvent: PointerEvent) => handleDragMoveRef.current(moveEvent)
    const onUp = (upEvent: PointerEvent) => {
      const drag = dragRef.current
      if (drag && upEvent.pointerId !== drag.pointerId) return
      element.removeEventListener('pointermove', onMove)
      element.removeEventListener('pointerup', onUp)
      element.removeEventListener('pointercancel', onUp)
      endDragRef.current()
    }

    element.addEventListener('pointermove', onMove)
    element.addEventListener('pointerup', onUp)
    element.addEventListener('pointercancel', onUp)
  }, [])

  // ---------------------------------------------------------------- panning

  const handleBackgroundPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0 && event.button !== 1) return
    setSelectedId(null)
    const element = event.currentTarget as HTMLElement
    element.setPointerCapture(event.pointerId)
    panRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY }

    const handleMove = (moveEvent: PointerEvent) => {
      const pan = panRef.current
      if (!pan || moveEvent.pointerId !== pan.pointerId) return
      panBy(moveEvent.clientX - pan.startX, moveEvent.clientY - pan.startY)
      pan.startX = moveEvent.clientX
      pan.startY = moveEvent.clientY
    }
    const handleUp = () => {
      panRef.current = null
      element.removeEventListener('pointermove', handleMove)
      element.removeEventListener('pointerup', handleUp)
      element.removeEventListener('pointercancel', handleUp)
    }

    element.addEventListener('pointermove', handleMove)
    element.addEventListener('pointerup', handleUp)
    element.addEventListener('pointercancel', handleUp)
  }

  // ---------------------------------------------------------------- keyboard

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (openId) setOpenId(null)
        else if (fullscreen) setFullscreen(false)
        return
      }
      const target = event.target as HTMLElement | null
      if (typeof target?.closest === 'function' && target.closest('input, textarea, [contenteditable="true"]')) return

      const modifier = event.ctrlKey || event.metaKey
      if (modifier && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
        return
      }
      if (modifier && event.key.toLowerCase() === 'y') {
        event.preventDefault()
        redo()
        return
      }
      if (!openId && selectedId && (event.key === 'Delete' || event.key === 'Backspace')) {
        event.preventDefault()
        removeCard(selectedId)
        setSelectedId(null)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreen, openId, redo, removeCard, selectedId, undo])

  // ---------------------------------------------------------------- initial fit

  useEffect(() => {
    if (didInitialFit.current) return
    const bounds = contentBounds(cards)
    if (!bounds || !containerRef.current?.clientHeight) return
    didInitialFit.current = true
    fitTo(bounds)
  }, [containerRef, fitTo, cards])

  // ---------------------------------------------------------------- render

  const openCard = openId ? cards.find((card) => card.id === openId) ?? null : null

  const toolbarButton =
    'rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-white'

  return (
    <div className={fullscreen ? 'fixed inset-0 z-50 flex flex-col gap-2 bg-white p-4' : 'space-y-2'}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <button type="button" onClick={addCard} className={toolbarButton}>
            {addButtonLabel}
          </button>
          <button
            type="button"
            onClick={tidyUp}
            disabled={cards.length === 0}
            className={toolbarButton}
            title="Re-arrange cards into a clean grid"
          >
            Tidy up
          </button>
          <button type="button" onClick={undo} disabled={!canUndo} className={toolbarButton} title="Undo (Ctrl+Z)">
            Undo
          </button>
          <button type="button" onClick={redo} disabled={!canRedo} className={toolbarButton} title="Redo (Ctrl+Shift+Z)">
            Redo
          </button>

          <span className="mx-1 h-5 w-px bg-gray-200" />

          <button type="button" onClick={() => zoomBy(1 / 1.2)} disabled={viewport.zoom <= MIN_ZOOM + 0.001} className={toolbarButton} title="Zoom out">
            &minus;
          </button>
          <button type="button" onClick={resetZoom} className={`${toolbarButton} w-14 tabular-nums`} title="Reset zoom to 100%">
            {Math.round(viewport.zoom * 100)}%
          </button>
          <button type="button" onClick={() => zoomBy(1.2)} disabled={viewport.zoom >= MAX_ZOOM - 0.001} className={toolbarButton} title="Zoom in">
            +
          </button>
          <button type="button" onClick={() => fitTo(contentBounds(cards))} className={toolbarButton} title="Fit everything in view">
            Fit
          </button>
          <button type="button" onClick={() => setFullscreen((current) => !current)} className={toolbarButton} title={fullscreen ? 'Exit fullscreen (Esc)' : 'Edit fullscreen'}>
            {fullscreen ? 'Exit' : 'Fullscreen'}
          </button>
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Click a card to edit it in a popup; drag it anywhere to organize. Cards snap to the grid &mdash; hold{' '}
        <kbd className="rounded border border-gray-300 px-1">Alt</kbd> to move freely. Ctrl+scroll zooms, dragging the background pans.
      </p>

      <div
        ref={containerRef}
        data-testid="working-memory-canvas"
        className={`relative w-full cursor-grab overflow-hidden rounded-xl border border-gray-200 bg-gray-50 active:cursor-grabbing ${
          fullscreen ? 'min-h-0 flex-1' : ''
        }`}
        style={{
          height: fullscreen ? undefined : 'min(70vh, 640px)',
          minHeight: fullscreen ? undefined : 420,
          backgroundImage:
            'linear-gradient(to right, #e5e7eb 1px, transparent 1px), linear-gradient(to bottom, #e5e7eb 1px, transparent 1px)',
          backgroundSize: `${GRID * viewport.zoom}px ${GRID * viewport.zoom}px`,
          backgroundPosition: `${viewport.panX}px ${viewport.panY}px`,
          touchAction: 'none',
        }}
        onPointerDown={handleBackgroundPointerDown}
      >
        <div
          className="absolute left-0 top-0"
          style={{ transform: `translate(${viewport.panX}px, ${viewport.panY}px) scale(${viewport.zoom})`, transformOrigin: '0 0' }}
        >
          {cards.map((card) => (
            <WorkingMemoryCanvasCard
              key={card.id}
              card={card}
              selected={selectedId === card.id}
              primaryLabel={primaryLabel}
              secondaryLabel={secondaryLabel}
              onPointerDown={handleItemPointerDown}
              onDuplicate={duplicateCard}
              onRemove={removeCard}
            />
          ))}

          <div ref={vGuideRef} className="pointer-events-none absolute bg-brand-500" style={{ display: 'none', top: -10000, height: 20000, width: 1, zIndex: 70 }} />
          <div ref={hGuideRef} className="pointer-events-none absolute bg-brand-500" style={{ display: 'none', left: -10000, width: 20000, height: 1, zIndex: 70 }} />
        </div>

        {cards.length === 0 ? (
          <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-gray-400">
            No cards yet. Add one to get started.
          </p>
        ) : null}
      </div>

      {openCard ? (
        <WorkingMemoryCardModal
          card={openCard}
          primaryLabel={primaryLabel}
          primaryPlaceholder={primaryPlaceholder}
          secondaryLabel={secondaryLabel}
          secondaryPlaceholder={secondaryPlaceholder}
          showDateTimeTokens={showDateTimeTokens}
          onChange={updateCard}
          onDuplicate={duplicateCard}
          onRemove={removeCard}
          onClose={() => setOpenId(null)}
        />
      ) : null}
    </div>
  )
}
