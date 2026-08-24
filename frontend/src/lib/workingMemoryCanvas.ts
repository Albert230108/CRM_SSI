/** Geometry helpers for the working-memory canvases (rules, fields) - the same drag/snap/tidy
 * mechanics as lib/aiTemplateCanvas.ts, trimmed to a generic two-field card with no post-it
 * notes and no meaningful prompt order (rules/fields are consumed as an unordered set).
 */
export const GRID = 24
export const CARD_WIDTH = 288
export const CARD_HEIGHT = 176
export const CARD_GAP = GRID
export const MIN_CARD_WIDTH = 220
export const MIN_CARD_HEIGHT = 120

const COLUMNS = 3

export type WorkingMemoryCard = {
  id: string
  serverId: number | null
  primary: string
  secondary: string
  status?: string
  x: number
  y: number
  w: number
  h: number
  z: number
}

export type Rect = { x: number; y: number; w: number; h: number }

export function nextCardPosition(count: number) {
  const column = count % COLUMNS
  const row = Math.floor(count / COLUMNS)
  return { x: column * (CARD_WIDTH + CARD_GAP), y: row * (CARD_HEIGHT + CARD_GAP) }
}

export function cardRect(card: WorkingMemoryCard): Rect {
  return { x: card.x, y: card.y, w: card.w, h: card.h }
}

export function maxZ(cards: WorkingMemoryCard[]) {
  return Math.max(0, ...cards.map((card) => card.z))
}

export function snapToGrid(value: number) {
  return Math.round(value / GRID) * GRID
}

export function contentBounds(cards: WorkingMemoryCard[]) {
  if (cards.length === 0) return null
  const rects = cards.map(cardRect)
  return {
    minX: Math.min(...rects.map((rect) => rect.x)),
    minY: Math.min(...rects.map((rect) => rect.y)),
    maxX: Math.max(...rects.map((rect) => rect.x + rect.w)),
    maxY: Math.max(...rects.map((rect) => rect.y + rect.h)),
  }
}

export type SnapResult = { x: number; y: number; guideX: number | null; guideY: number | null }

const ALIGN_TOLERANCE = 6

export function snapRect(moving: Rect, others: Rect[]): SnapResult {
  let x = snapToGrid(moving.x)
  let y = snapToGrid(moving.y)
  let guideX: number | null = null
  let guideY: number | null = null

  let bestX = ALIGN_TOLERANCE
  let bestY = ALIGN_TOLERANCE

  for (const other of others) {
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

/** Re-lays cards into rows by their current array order - used only by "Tidy up". */
export function tidyLayout(cards: WorkingMemoryCard[]): WorkingMemoryCard[] {
  const rowWidth = COLUMNS * (CARD_WIDTH + CARD_GAP)
  let x = 0
  let y = 0
  let rowHeight = 0

  return cards.map((card) => {
    if (x > 0 && x + card.w > rowWidth) {
      x = 0
      y += rowHeight + CARD_GAP
      rowHeight = 0
    }
    const placed = { ...card, x, y }
    x += card.w + CARD_GAP
    rowHeight = Math.max(rowHeight, card.h)
    return placed
  })
}
