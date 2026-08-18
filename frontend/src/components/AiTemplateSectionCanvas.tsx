import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AiTemplateNote, AiTemplateSection, BrainSectionOption } from '../types/aiReplyTemplate'
import { MAX_ZOOM, MIN_ZOOM, useCanvasViewport } from '../hooks/useCanvasViewport'
import {
  CARD_HEIGHT,
  CARD_WIDTH,
  GRID,
  MIN_CARD_HEIGHT,
  MIN_CARD_WIDTH,
  MIN_NOTE_HEIGHT,
  MIN_NOTE_WIDTH,
  NOTE_COLORS,
  NOTE_HEIGHT,
  NOTE_WIDTH,
  contentBounds,
  maxZ,
  nextSectionPosition,
  noteRect,
  noteZ,
  sectionRect,
  sectionZ,
  snapRect,
  snapToGrid,
  tidyLayout,
  type Rect,
} from '../lib/aiTemplateCanvas'
import AiTemplateCanvasCard from './AiTemplateCanvasCard'
import AiTemplateCanvasNote from './AiTemplateCanvasNote'
import { AiTemplateNoteModal, AiTemplateSectionModal } from './AiTemplateSectionModal'

const DRAG_THRESHOLD = 4
const HISTORY_LIMIT = 50

type ItemKind = 'section' | 'note'
type Snapshot = { sections: AiTemplateSection[]; notes: AiTemplateNote[] }
type OpenItem = { kind: ItemKind; id: string }

type DragState = {
  kind: ItemKind
  id: string
  mode: 'move' | 'resize'
  pointerId: number
  element: HTMLElement
  startClientX: number
  startClientY: number
  origin: Rect
  next: Rect
  moved: boolean
  snapshot: Snapshot
  frame: number | null
}

type Props = {
  sections: AiTemplateSection[]
  notes: AiTemplateNote[]
  onSectionsChange: (sections: AiTemplateSection[]) => void
  onNotesChange: (notes: AiTemplateNote[]) => void
  contentPlaceholderHint: string
  brainSections: BrainSectionOption[]
  /** Scopes the persisted zoom/pan to one template. */
  viewportKey: string
}

export default function AiTemplateSectionCanvas({
  sections,
  notes,
  onSectionsChange,
  onNotesChange,
  contentPlaceholderHint,
  brainSections,
  viewportKey,
}: Props) {
  const { containerRef, viewport, viewportRef, hasRestoredViewport, zoomBy, resetZoom, panBy, fitTo, toCanvas } =
    useCanvasViewport(viewportKey)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [openItem, setOpenItem] = useState<OpenItem | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  // Bumped whenever the undo/redo stacks change, so the toolbar re-renders. The stacks themselves
  // live in refs because the pointer handlers push to them mid-gesture.
  const [historyVersion, setHistoryVersion] = useState(0)

  // Live mirrors so handlers registered for one gesture never read a stale array.
  const sectionsRef = useRef(sections)
  sectionsRef.current = sections
  const notesRef = useRef(notes)
  notesRef.current = notes

  const undoRef = useRef<Snapshot[]>([])
  const redoRef = useRef<Snapshot[]>([])
  const dragRef = useRef<DragState | null>(null)
  const panRef = useRef<{ pointerId: number; startX: number; startY: number } | null>(null)
  const vGuideRef = useRef<HTMLDivElement | null>(null)
  const hGuideRef = useRef<HTMLDivElement | null>(null)
  const didInitialFit = useRef(hasRestoredViewport)

  const orderedSections = useMemo(
    () => [...sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
    [sections],
  )

  const orderIndexById = useMemo(() => {
    const map = new Map<string, number>()
    orderedSections.forEach((section, index) => map.set(section.id as string, index))
    return map
  }, [orderedSections])

  /** Sections and notes interleaved by z, so stacking is one shared order across both kinds. */
  const stackedItems = useMemo(() => {
    const items = [
      ...sections.map((section, index) => ({
        key: `section:${section.id}`,
        kind: 'section' as const,
        z: sectionZ(section, index),
        section,
      })),
      ...notes.map((note, index) => ({
        key: `note:${note.id}`,
        kind: 'note' as const,
        z: noteZ(note, index),
        note,
      })),
    ]
    return items.sort((a, b) => a.z - b.z)
  }, [sections, notes])

  // ---------------------------------------------------------------- history

  const snapshot = useCallback((): Snapshot => ({ sections: sectionsRef.current, notes: notesRef.current }), [])

  const pushHistory = useCallback((previous: Snapshot) => {
    undoRef.current = [...undoRef.current.slice(-(HISTORY_LIMIT - 1)), previous]
    redoRef.current = []
    setHistoryVersion((current) => current + 1)
  }, [])

  const applySnapshot = useCallback(
    (next: Snapshot) => {
      onSectionsChange(next.sections)
      onNotesChange(next.notes)
    },
    [onSectionsChange, onNotesChange],
  )

  const undo = useCallback(() => {
    const previous = undoRef.current[undoRef.current.length - 1]
    if (!previous) return
    undoRef.current = undoRef.current.slice(0, -1)
    redoRef.current = [...redoRef.current, snapshot()]
    applySnapshot(previous)
    setHistoryVersion((current) => current + 1)
  }, [applySnapshot, snapshot])

  const redo = useCallback(() => {
    const next = redoRef.current[redoRef.current.length - 1]
    if (!next) return
    redoRef.current = redoRef.current.slice(0, -1)
    undoRef.current = [...undoRef.current, snapshot()]
    applySnapshot(next)
    setHistoryVersion((current) => current + 1)
  }, [applySnapshot, snapshot])

  const { canUndo, canRedo } = useMemo(
    () => ({ canUndo: undoRef.current.length > 0, canRedo: redoRef.current.length > 0 }),
    [historyVersion],
  )

  // Text edits in the popup are recorded as one undo step: the state as it was when the popup
  // opened, pushed on the first keystroke.
  const editBaselineRef = useRef<{ pushed: boolean; snapshot: Snapshot } | null>(null)
  useEffect(() => {
    editBaselineRef.current = openItem ? { pushed: false, snapshot: snapshot() } : null
  }, [openItem, snapshot])

  const recordEdit = useCallback(() => {
    const baseline = editBaselineRef.current
    if (!baseline || baseline.pushed) return
    baseline.pushed = true
    pushHistory(baseline.snapshot)
  }, [pushHistory])

  // ---------------------------------------------------------------- mutations

  const addSection = () => {
    pushHistory(snapshot())
    const position = nextSectionPosition(sections.length)
    const section: AiTemplateSection = {
      id: crypto.randomUUID(),
      label: '',
      content: '',
      order: sections.length,
      x: position.x,
      y: position.y,
      w: CARD_WIDTH,
      h: CARD_HEIGHT,
      z: maxZ(sections, notes) + 1,
    }
    onSectionsChange([...sections, section])
    setOpenItem({ kind: 'section', id: section.id as string })
  }

  const addNote = () => {
    pushHistory(snapshot())
    // Drop new notes near the middle of whatever the user is currently looking at.
    const element = containerRef.current
    let centre = { x: 0, y: 0 }
    if (element) {
      const rect = element.getBoundingClientRect()
      centre = toCanvas(rect.left + element.clientWidth / 2, rect.top + element.clientHeight / 3)
    }
    const note: AiTemplateNote = {
      id: crypto.randomUUID(),
      text: '',
      x: snapToGrid(centre.x - NOTE_WIDTH / 2) + (notes.length % 3) * GRID,
      y: snapToGrid(centre.y - NOTE_HEIGHT / 2) + (notes.length % 3) * GRID,
      color: NOTE_COLORS[notes.length % NOTE_COLORS.length],
      w: NOTE_WIDTH,
      h: NOTE_HEIGHT,
      z: maxZ(sections, notes) + 1,
    }
    onNotesChange([...notes, note])
    setOpenItem({ kind: 'note', id: note.id })
  }

  const removeSection = useCallback(
    (id: string) => {
      pushHistory(snapshot())
      setOpenItem((current) => (current?.kind === 'section' && current.id === id ? null : current))
      onSectionsChange(
        sectionsRef.current
          .filter((section) => section.id !== id)
          .map((section, index) => ({ ...section, order: index })),
      )
    },
    [onSectionsChange, pushHistory, snapshot],
  )

  const removeNote = useCallback(
    (id: string) => {
      pushHistory(snapshot())
      setOpenItem((current) => (current?.kind === 'note' && current.id === id ? null : current))
      onNotesChange(notesRef.current.filter((note) => note.id !== id))
    },
    [onNotesChange, pushHistory, snapshot],
  )

  const duplicateSection = useCallback(
    (id: string) => {
      const source = sectionsRef.current.find((section) => section.id === id)
      if (!source) return
      pushHistory(snapshot())
      const rect = sectionRect(source)
      const copy: AiTemplateSection = {
        ...source,
        id: crypto.randomUUID(),
        x: rect.x + GRID,
        y: rect.y + GRID,
        order: sectionsRef.current.length,
        z: maxZ(sectionsRef.current, notesRef.current) + 1,
      }
      onSectionsChange([...sectionsRef.current, copy])
      setOpenItem({ kind: 'section', id: copy.id as string })
    },
    [onSectionsChange, pushHistory, snapshot],
  )

  const updateSection = useCallback(
    (id: string, field: 'label' | 'content', value: string) => {
      recordEdit()
      onSectionsChange(
        sectionsRef.current.map((section) => (section.id === id ? { ...section, [field]: value } : section)),
      )
    },
    [onSectionsChange, recordEdit],
  )

  const updateNote = useCallback(
    (id: string, field: 'text' | 'color', value: string) => {
      recordEdit()
      onNotesChange(notesRef.current.map((note) => (note.id === id ? { ...note, [field]: value } : note)))
    },
    [onNotesChange, recordEdit],
  )

  const moveOrder = useCallback(
    (id: string, direction: -1 | 1) => {
      const sorted = [...sectionsRef.current].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
      const index = sorted.findIndex((section) => section.id === id)
      const targetIndex = index + direction
      if (index === -1 || targetIndex < 0 || targetIndex >= sorted.length) return
      pushHistory(snapshot())
      const [moved] = sorted.splice(index, 1)
      sorted.splice(targetIndex, 0, moved)
      onSectionsChange(sorted.map((section, position) => ({ ...section, order: position })))
    },
    [onSectionsChange, pushHistory, snapshot],
  )

  const tidyUp = () => {
    if (sections.length === 0) return
    pushHistory(snapshot())
    onSectionsChange(tidyLayout(sections))
  }

  /** Raises an item above every other item. Deliberately not an undo step of its own. */
  const bringToFront = useCallback(
    (kind: ItemKind, id: string) => {
      const top = maxZ(sectionsRef.current, notesRef.current)
      if (kind === 'section') {
        const current = sectionsRef.current.find((section) => section.id === id)
        if (!current || current.z === top) return
        onSectionsChange(
          sectionsRef.current.map((section) => (section.id === id ? { ...section, z: top + 1 } : section)),
        )
      } else {
        const current = notesRef.current.find((note) => note.id === id)
        if (!current || current.z === top) return
        onNotesChange(notesRef.current.map((note) => (note.id === id ? { ...note, z: top + 1 } : note)))
      }
    },
    [onNotesChange, onSectionsChange],
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
          const others: Rect[] = [
            ...sectionsRef.current
              .filter((section) => !(drag.kind === 'section' && section.id === drag.id))
              .map(sectionRect),
            ...notesRef.current.filter((note) => !(drag.kind === 'note' && note.id === drag.id)).map(noteRect),
          ]
          const snapped = snapRect(candidate, others)
          drag.next = { ...candidate, x: snapped.x, y: snapped.y }
          showGuides(snapped.guideX, snapped.guideY)
        }
      } else {
        const minWidth = drag.kind === 'section' ? MIN_CARD_WIDTH : MIN_NOTE_WIDTH
        const minHeight = drag.kind === 'section' ? MIN_CARD_HEIGHT : MIN_NOTE_HEIGHT
        let w = drag.origin.w + dx
        let h = drag.origin.h + dy
        if (!free) {
          w = snapToGrid(w)
          h = snapToGrid(h)
        }
        drag.next = { ...drag.origin, w: Math.max(minWidth, w), h: Math.max(minHeight, h) }
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

    // Under the threshold this was a click, not a drag: open the popup editor.
    if (!drag.moved) {
      bringToFront(drag.kind, drag.id)
      setOpenItem({ kind: drag.kind, id: drag.id })
      return
    }

    pushHistory(drag.snapshot)
    const top = maxZ(sectionsRef.current, notesRef.current)
    if (drag.kind === 'section') {
      onSectionsChange(
        sectionsRef.current.map((section) =>
          section.id === drag.id
            ? {
                ...section,
                x: drag.next.x,
                y: drag.next.y,
                w: drag.next.w,
                h: drag.next.h,
                z: section.z === top ? section.z : top + 1,
              }
            : section,
        ),
      )
    } else {
      onNotesChange(
        notesRef.current.map((note) =>
          note.id === drag.id
            ? {
                ...note,
                x: drag.next.x,
                y: drag.next.y,
                w: drag.next.w,
                h: drag.next.h,
                z: note.z === top ? note.z : top + 1,
              }
            : note,
        ),
      )
    }
  }, [bringToFront, hideGuides, onNotesChange, onSectionsChange, pushHistory])

  // Ref-forwarded so the per-gesture listeners below can stay identity-stable.
  const handleDragMoveRef = useRef(handleDragMove)
  handleDragMoveRef.current = handleDragMove
  const endDragRef = useRef(endDrag)
  endDragRef.current = endDrag

  const handleItemPointerDown = useCallback(
    (event: React.PointerEvent, kind: ItemKind, id: string, mode: 'move' | 'resize') => {
      if (event.button !== 0) return
      // The card's own buttons (order, duplicate, delete) must stay clickable.
      if (mode === 'move' && (event.target as HTMLElement).closest('button')) return

      const element = (event.target as HTMLElement).closest('[data-canvas-item]') as HTMLElement | null
      if (!element) return

      const source =
        kind === 'section'
          ? sectionsRef.current.find((section) => section.id === id)
          : notesRef.current.find((note) => note.id === id)
      if (!source) return
      const origin =
        kind === 'section' ? sectionRect(source as AiTemplateSection) : noteRect(source as AiTemplateNote)

      // Stops the canvas background from also starting a pan.
      event.stopPropagation()
      setSelectedId(id)
      element.setPointerCapture(event.pointerId)
      element.style.zIndex = '60'

      dragRef.current = {
        kind,
        id,
        mode,
        pointerId: event.pointerId,
        element,
        startClientX: event.clientX,
        startClientY: event.clientY,
        origin,
        next: origin,
        moved: false,
        snapshot: { sections: sectionsRef.current, notes: notesRef.current },
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
    },
    [],
  )

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
        if (openItem) setOpenItem(null)
        else if (fullscreen) setFullscreen(false)
        return
      }
      // Never hijack keys while a field has focus: the browser's own textarea undo must keep working.
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
      if (!openItem && selectedId && (event.key === 'Delete' || event.key === 'Backspace')) {
        event.preventDefault()
        if (sectionsRef.current.some((section) => section.id === selectedId)) removeSection(selectedId)
        else removeNote(selectedId)
        setSelectedId(null)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreen, openItem, redo, removeNote, removeSection, selectedId, undo])

  // ---------------------------------------------------------------- initial fit

  useEffect(() => {
    if (didInitialFit.current) return
    const bounds = contentBounds(sections, notes)
    if (!bounds || !containerRef.current?.clientHeight) return
    didInitialFit.current = true
    fitTo(bounds)
  }, [containerRef, fitTo, notes, sections])

  // ---------------------------------------------------------------- render

  const openSection =
    openItem?.kind === 'section' ? sections.find((section) => section.id === openItem.id) ?? null : null
  const openNote = openItem?.kind === 'note' ? notes.find((note) => note.id === openItem.id) ?? null : null

  const stepSection = (direction: -1 | 1) => {
    if (!openSection || orderedSections.length < 2) return
    const index = orderIndexById.get(openSection.id as string) ?? 0
    const next = orderedSections[(index + direction + orderedSections.length) % orderedSections.length]
    if (next) setOpenItem({ kind: 'section', id: next.id as string })
  }

  const toolbarButton =
    'rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40 disabled:hover:bg-white'

  return (
    <div className={fullscreen ? 'fixed inset-0 z-50 flex flex-col gap-2 bg-white p-4' : 'space-y-2'}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">1. Template text (subprompts)</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={addNote}
            className="rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-xs font-semibold text-amber-800 hover:bg-amber-100"
          >
            + Post-it
          </button>
          <button type="button" onClick={addSection} className={toolbarButton}>
            + Section
          </button>
          <button
            type="button"
            onClick={tidyUp}
            disabled={sections.length === 0}
            className={toolbarButton}
            title="Re-arrange cards into a clean grid in prompt order"
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

          <button
            type="button"
            onClick={() => zoomBy(1 / 1.2)}
            disabled={viewport.zoom <= MIN_ZOOM + 0.001}
            className={toolbarButton}
            title="Zoom out"
          >
            &minus;
          </button>
          <button type="button" onClick={resetZoom} className={`${toolbarButton} w-14 tabular-nums`} title="Reset zoom to 100%">
            {Math.round(viewport.zoom * 100)}%
          </button>
          <button
            type="button"
            onClick={() => zoomBy(1.2)}
            disabled={viewport.zoom >= MAX_ZOOM - 0.001}
            className={toolbarButton}
            title="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => fitTo(contentBounds(sections, notes))}
            className={toolbarButton}
            title="Fit everything in view"
          >
            Fit
          </button>
          <button
            type="button"
            onClick={() => setFullscreen((current) => !current)}
            className={toolbarButton}
            title={fullscreen ? 'Exit fullscreen (Esc)' : 'Edit fullscreen'}
          >
            {fullscreen ? 'Exit' : 'Fullscreen'}
          </button>
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Click a card to edit it in a popup; drag it anywhere to organize. The numbered badge (not position) is the order
        sent to the AI. Cards snap to the grid &mdash; hold <kbd className="rounded border border-gray-300 px-1">Alt</kbd> to
        move freely. Ctrl+scroll zooms, dragging the background pans. Post-it notes are never sent to the AI.
      </p>

      <div
        ref={containerRef}
        data-testid="ai-template-canvas"
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
          style={{
            transform: `translate(${viewport.panX}px, ${viewport.panY}px) scale(${viewport.zoom})`,
            transformOrigin: '0 0',
          }}
        >
          {stackedItems.map((item) =>
            item.kind === 'section' ? (
              <AiTemplateCanvasCard
                key={item.key}
                section={item.section}
                orderIndex={orderIndexById.get(item.section.id as string) ?? 0}
                orderTotal={orderedSections.length}
                selected={selectedId === item.section.id}
                onPointerDown={handleItemPointerDown}
                onMoveOrder={moveOrder}
                onDuplicate={duplicateSection}
                onRemove={removeSection}
              />
            ) : (
              <AiTemplateCanvasNote
                key={item.key}
                note={item.note}
                selected={selectedId === item.note.id}
                onPointerDown={handleItemPointerDown}
                onRemove={removeNote}
              />
            ),
          )}

          <div
            ref={vGuideRef}
            className="pointer-events-none absolute bg-cyan-500"
            style={{ display: 'none', top: -10000, height: 20000, width: 1, zIndex: 70 }}
          />
          <div
            ref={hGuideRef}
            className="pointer-events-none absolute bg-cyan-500"
            style={{ display: 'none', left: -10000, width: 20000, height: 1, zIndex: 70 }}
          />
        </div>

        {sections.length === 0 && notes.length === 0 ? (
          <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-gray-400">
            No sections yet &mdash; add one to start building the prompt.
          </p>
        ) : null}
      </div>

      {openSection ? (
        <AiTemplateSectionModal
          section={openSection}
          orderIndex={orderIndexById.get(openSection.id as string) ?? 0}
          orderTotal={orderedSections.length}
          brainSections={brainSections}
          contentPlaceholderHint={contentPlaceholderHint}
          onChange={updateSection}
          onMoveOrder={moveOrder}
          onStep={stepSection}
          onDuplicate={duplicateSection}
          onRemove={removeSection}
          onClose={() => setOpenItem(null)}
        />
      ) : null}

      {openNote ? (
        <AiTemplateNoteModal note={openNote} onChange={updateNote} onRemove={removeNote} onClose={() => setOpenItem(null)} />
      ) : null}
    </div>
  )
}
