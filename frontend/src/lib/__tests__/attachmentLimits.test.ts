import { describe, expect, it } from 'vitest'

import {
  MAX_EMAIL_TOTAL_BYTES,
  MAX_FILE_BYTES,
  MAX_WHATSAPP_TOTAL_BYTES,
  formatBytes,
  maxTotalBytesFor,
  validateAttachmentSelection,
} from '../attachmentLimits'

const file = (name: string, size: number) => ({ name, size })

describe('maxTotalBytesFor', () => {
  it('caps email lower than WhatsApp because of Gmail\'s raw-send ceiling', () => {
    expect(maxTotalBytesFor('email')).toBe(MAX_EMAIL_TOTAL_BYTES)
    expect(maxTotalBytesFor('whatsapp')).toBe(MAX_WHATSAPP_TOTAL_BYTES)
    expect(maxTotalBytesFor('email')).toBeLessThan(maxTotalBytesFor('whatsapp'))
  })
})

describe('validateAttachmentSelection', () => {
  it('accepts a file under both caps', () => {
    expect(validateAttachmentSelection([file('a.pdf', 1024)], 'email')).toEqual([])
  })

  it('rejects a file over the per-file cap', () => {
    const errors = validateAttachmentSelection([file('big.bin', MAX_FILE_BYTES + 1)], 'whatsapp')
    expect(errors).toHaveLength(1)
    expect(errors[0].filename).toBe('big.bin')
    expect(errors[0].reason).toContain('per-file limit')
  })

  it('rejects the file that pushes the running total past the channel cap', () => {
    const eightMb = 8 * 1024 * 1024
    const files = [file('a.bin', eightMb), file('b.bin', eightMb), file('c.bin', eightMb)]

    const errors = validateAttachmentSelection(files, 'email')

    // 8+8 fits under 20MB; the third crosses it.
    expect(errors.map((item) => item.filename)).toEqual(['c.bin'])
    expect(errors[0].reason).toContain('total limit for email')
  })

  it('counts already-selected bytes against the total', () => {
    const errors = validateAttachmentSelection(
      [file('extra.bin', 5 * 1024 * 1024)],
      'email',
      MAX_EMAIL_TOTAL_BYTES - 1024,
    )
    expect(errors).toHaveLength(1)
  })

  it('does not count an oversize file toward the running total', () => {
    const files = [file('huge.bin', MAX_FILE_BYTES + 1), file('small.bin', 1024)]

    const errors = validateAttachmentSelection(files, 'email')

    expect(errors.map((item) => item.filename)).toEqual(['huge.bin'])
  })

  it('allows the same selection on WhatsApp that overflows on email', () => {
    // 22MB total, each file under the 10MB per-file cap: over the 20MB email limit but
    // inside the 25MB WhatsApp one.
    const files = [file('a.bin', 8 * 1024 * 1024), file('b.bin', 8 * 1024 * 1024), file('c.bin', 6 * 1024 * 1024)]

    expect(validateAttachmentSelection(files, 'email')).toHaveLength(1)
    expect(validateAttachmentSelection(files, 'whatsapp')).toHaveLength(0)
  })
})

describe('formatBytes', () => {
  it('scales the unit to the size', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
  })
})
