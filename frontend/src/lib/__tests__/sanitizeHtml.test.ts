import { describe, expect, it } from 'vitest'
import { sanitizeHtml } from '../sanitizeHtml'

describe('sanitizeHtml', () => {
  it('keeps semantic strikethrough tags', () => {
    expect(sanitizeHtml('<s>x</s>')).toContain('<s>x</s>')
  })

  it('still strips disallowed tags and style attributes', () => {
    expect(sanitizeHtml('<span style="color:red">x</span>')).toBe('<span>x</span>')
    expect(sanitizeHtml('<script>alert(1)</script>x')).toBe('x')
  })
})
