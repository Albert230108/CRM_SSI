import { describe, expect, it } from 'vitest'
import { htmlToPlainText, sanitizeComposerHtml, whatsappHtmlToMarkup, whatsappMarkupToHtml } from '../messageFormatting'

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

describe('sanitizeComposerHtml', () => {
  // Regression: dragging/resizing the reply dialog blurs the editor and re-runs this sanitize over
  // the live DOM. Style-based formatting emitted by execCommand must survive as semantic tags
  // instead of collapsing to raw text.
  it('preserves style-based bold as a semantic tag', () => {
    expect(sanitizeComposerHtml('<span style="font-weight:bold">hi</span>')).toContain('<strong>hi</strong>')
  })

  it('preserves numeric font-weight bold', () => {
    expect(sanitizeComposerHtml('<span style="font-weight:700">hi</span>')).toContain('<strong>hi</strong>')
  })

  it('keeps already-semantic bold intact', () => {
    expect(sanitizeComposerHtml('<b>hi</b>')).toContain('<b>hi</b>')
  })

  it('preserves style-based italic', () => {
    expect(sanitizeComposerHtml('<span style="font-style:italic">hi</span>')).toContain('<em>hi</em>')
  })

  it('preserves style-based underline', () => {
    expect(sanitizeComposerHtml('<span style="text-decoration:underline">hi</span>')).toContain('<u>hi</u>')
  })

  it('preserves style-based and legacy strikethrough', () => {
    expect(sanitizeComposerHtml('<span style="text-decoration:line-through">hi</span>')).toContain('<s>hi</s>')
    expect(sanitizeComposerHtml('<strike>hi</strike>')).toContain('<s>hi</s>')
  })

  it('does not leave the stripped style attribute behind', () => {
    expect(sanitizeComposerHtml('<span style="font-weight:bold">hi</span>')).not.toContain('style=')
  })
})

describe('whatsapp formatting round-trip', () => {
  it('reads style-based bold as markup', () => {
    expect(whatsappHtmlToMarkup('<span style="font-weight:bold">hi</span>')).toBe('*hi*')
  })

  it('reads strikethrough as markup', () => {
    expect(whatsappHtmlToMarkup('<s>hi</s>')).toBe('~hi~')
  })

  it('round-trips bold, italic and strikethrough markup', () => {
    expect(whatsappHtmlToMarkup(whatsappMarkupToHtml('*a* _b_ ~c~'))).toBe('*a* _b_ ~c~')
  })
})
