const BLOCK_TAGS = new Set(['ADDRESS', 'ARTICLE', 'BLOCKQUOTE', 'DIV', 'DL', 'DT', 'DD', 'FIELDSET', 'FIGCAPTION', 'FIGURE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'LI', 'OL', 'P', 'PRE', 'SECTION', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'UL'])
const ALLOWED_TAGS = new Set(['A', 'B', 'BR', 'CODE', 'DIV', 'EM', 'I', 'LI', 'OL', 'P', 'PRE', 'S', 'SPAN', 'STRONG', 'SUB', 'SUP', 'U', 'UL', 'BLOCKQUOTE'])
const ALLOWED_ATTRS = new Set(['href', 'title', 'target', 'rel'])

const QUOTE_CONTAINER_CLASS_PATTERN = /(?:^|\s)(gmail_quote|gmail_quote_container|yahoo_quoted|protonmail_quote|moz-cite-prefix|gmail_attr)(?:\s|$)/i

export const removeQuotedReplyElements = (root: HTMLElement) => {
  Array.from(root.querySelectorAll('*')).forEach((node) => {
    if (!node.isConnected) return
    const el = node as HTMLElement
    const isQuoteContainer =
      QUOTE_CONTAINER_CLASS_PATTERN.test(el.className || '') ||
      (el.tagName === 'BLOCKQUOTE' && (el.getAttribute('type') || '').toLowerCase() === 'cite')
    if (isQuoteContainer) el.remove()
  })
}

export const sanitizeHtml = (html: string) => {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  removeQuotedReplyElements(doc.body)
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) return
    if (!(node instanceof HTMLElement)) return
    if (!ALLOWED_TAGS.has(node.tagName)) {
      const parent = node.parentNode
      if (!parent) return
      while (node.firstChild) parent.insertBefore(node.firstChild, node)
      parent.removeChild(node)
      return
    }
    Array.from(node.attributes).forEach((attr) => {
      if (!ALLOWED_ATTRS.has(attr.name.toLowerCase())) {
        node.removeAttribute(attr.name)
        return
      }
      if (attr.name.toLowerCase() === 'href') {
        const value = attr.value.trim()
        if (!/^https?:|^mailto:|^tel:/i.test(value)) {
          node.removeAttribute(attr.name)
          return
        }
        node.setAttribute('target', '_blank')
        node.setAttribute('rel', 'noreferrer noopener')
      }
    })
    Array.from(node.childNodes).forEach(walk)
  }
  Array.from(doc.body.childNodes).forEach(walk)
  return doc.body.innerHTML
}

export const SANITIZE_HTML_BLOCK_TAGS = BLOCK_TAGS
