import { describe, expect, it } from 'vitest'
import { htmlToPlainText } from '../messageFormatting'

describe('htmlToPlainText', () => {
  it('preserves link urls in plain-text output', () => {
    expect(htmlToPlainText('<p>Visit <a href="https://example.com">Example</a> now</p>')).toBe(
      'Visit Example (https://example.com) now',
    )
  })

  it('renders bare links as urls', () => {
    expect(htmlToPlainText('<p><a href="https://example.com">https://example.com</a></p>')).toBe('https://example.com')
  })
})
