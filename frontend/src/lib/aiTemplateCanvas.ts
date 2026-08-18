import type { AiTemplateNote, AiTemplateSection } from '../types/aiReplyTemplate'

/** Post-it palette, cycled when a new note is created. */
export const NOTE_COLORS = ['#fef08a', '#bbf7d0', '#bfdbfe', '#fbcfe8', '#fed7aa']

/** Everything is a multiple of the drawn grid so snapping lands on visible lines. */
export const GRID = 24
export const CARD_WIDTH = 288
export const CARD_HEIGHT = 192
export const CARD_GAP = GRID
export const NOTE_WIDTH = 168
export const NOTE_HEIGHT = 144
export const MIN_CARD_WIDTH = 192
export const MIN_CARD_HEIGHT = 120
export const MIN_NOTE_WIDTH = 120
export const MIN_NOTE_HEIGHT = 96

const COLUMNS = 3

/** Notes sit above sections by default, matching how the canvas looked before z existed. */
export const NOTE_Z_BASE = 1000

export type Rect = { x: number; y: number; w: number; h: number }

export function nextSectionPosition(count: number) {
  const column = count % COLUMNS
  const row = Math.floor(count / COLUMNS)
  return { x: column * (CARD_WIDTH + CARD_GAP), y: row * (CARD_HEIGHT + CARD_GAP) }
}

export function sectionRect(section: AiTemplateSection): Rect {
  return {
    x: section.x ?? 0,
    y: section.y ?? 0,
    w: section.w ?? CARD_WIDTH,
    h: section.h ?? CARD_HEIGHT,
  }
}

export function noteRect(note: AiTemplateNote): Rect {
  return {
    x: note.x,
    y: note.y,
    w: note.w ?? NOTE_WIDTH,
    h: note.h ?? NOTE_HEIGHT,
  }
}

export function sectionZ(section: AiTemplateSection, index: number) {
  return section.z ?? section.order ?? index
}

export function noteZ(note: AiTemplateNote, index: number) {
  return note.z ?? NOTE_Z_BASE + index
}

export function maxZ(sections: AiTemplateSection[], notes: AiTemplateNote[]) {
  return Math.max(
    0,
    ...sections.map((section, index) => sectionZ(section, index)),
    ...notes.map((note, index) => noteZ(note, index)),
  )
}

export function snapToGrid(value: number) {
  return Math.round(value / GRID) * GRID
}

/** Bounding box of every item on the canvas, or null when the canvas is empty. */
export function contentBounds(sections: AiTemplateSection[], notes: AiTemplateNote[]) {
  const rects = [...sections.map(sectionRect), ...notes.map(noteRect)]
  if (rects.length === 0) return null
  return {
    minX: Math.min(...rects.map((rect) => rect.x)),
    minY: Math.min(...rects.map((rect) => rect.y)),
    maxX: Math.max(...rects.map((rect) => rect.x + rect.w)),
    maxY: Math.max(...rects.map((rect) => rect.y + rect.h)),
  }
}

export type SnapResult = { x: number; y: number; guideX: number | null; guideY: number | null }

const ALIGN_TOLERANCE = 6

/**
 * Snaps a dragged rect to the grid, but prefers aligning with a neighbour's edge or centre when
 * one is within tolerance. The returned guide coordinates are where to draw the alignment lines.
 */
export function snapRect(moving: Rect, others: Rect[]): SnapResult {
  let x = snapToGrid(moving.x)
  let y = snapToGrid(moving.y)
  let guideX: number | null = null
  let guideY: number | null = null

  let bestX = ALIGN_TOLERANCE
  let bestY = ALIGN_TOLERANCE

  for (const other of others) {
    // [candidate left edge for `moving`, where the guide line is drawn]
    const xCandidates: Array<[number, number]> = [
      [other.x, other.x],
      [other.x + other.w - moving.w, other.x + other.w],
      [other.x + other.w / 2 - moving.w / 2, other.x + other.w / 2],
    ]
    for (const [candidate, guide] of xCandidates) {
      const distance = Math.abs(candidate - moving.x)
      if (distance <= bestX) {
        bestX = distance
        x = candidate
        guideX = guide
      }
    }

    const yCandidates: Array<[number, number]> = [
      [other.y, other.y],
      [other.y + other.h - moving.h, other.y + other.h],
      [other.y + other.h / 2 - moving.h / 2, other.y + other.h / 2],
    ]
    for (const [candidate, guide] of yCandidates) {
      const distance = Math.abs(candidate - moving.y)
      if (distance <= bestY) {
        bestY = distance
        y = candidate
        guideY = guide
      }
    }
  }

  return { x, y, guideX, guideY }
}

/**
 * Re-lays sections into rows in prompt order, honouring each card's own size so resized cards
 * do not overlap. Notes are deliberately left where the user put them.
 */
export function tidyLayout(sections: AiTemplateSection[]): AiTemplateSection[] {
  const rowWidth = COLUMNS * (CARD_WIDTH + CARD_GAP)
  let x = 0
  let y = 0
  let rowHeight = 0

  return [...sections]
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .map((section) => {
      const { w, h } = sectionRect(section)
      if (x > 0 && x + w > rowWidth) {
        x = 0
        y += rowHeight + CARD_GAP
        rowHeight = 0
      }
      const placed = { ...section, x, y }
      x += w + CARD_GAP
      rowHeight = Math.max(rowHeight, h)
      return placed
    })
}
