import { describe, expect, it } from 'vitest'
import { computeNights } from '../date'

describe('computeNights', () => {
  it('counts nights between two stay dates', () => {
    expect(computeNights('2026-08-12', '2026-08-19')).toBe(7)
  })

  it('counts a single night', () => {
    expect(computeNights('2026-08-12', '2026-08-13')).toBe(1)
  })

  it('ignores times attached to the stay dates', () => {
    expect(computeNights('2026-08-12T15:00:00', '2026-08-14T10:00:00')).toBe(2)
  })

  it('returns null when a date is missing, empty or unparseable', () => {
    expect(computeNights(null, '2026-08-19')).toBeNull()
    expect(computeNights('2026-08-12', null)).toBeNull()
    expect(computeNights('', '')).toBeNull()
    expect(computeNights('not-a-date', '2026-08-19')).toBeNull()
  })

  it('returns null for same-day or reversed stay dates', () => {
    expect(computeNights('2026-08-12', '2026-08-12')).toBeNull()
    expect(computeNights('2026-08-19', '2026-08-12')).toBeNull()
  })
})
