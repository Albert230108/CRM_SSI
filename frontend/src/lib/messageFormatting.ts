import { SANITIZE_HTML_BLOCK_TAGS, sanitizeHtml } from './sanitizeHtml'

export type ComposerBodyFormat = 'plain' | 'email_html' | 'whatsapp_rich'

const escapeHtml = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const decodeHtmlEntities = (value: string) => {
  const textarea = document.createElement('textarea')
  textarea.innerHTML = value
  return textarea.value
}

export const htmlToPlainText = (html: string) => {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const chunks: string[] = []
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent || ''
      if (text.trim()) chunks.push(text)
      return
    }
    if (!(node instanceof HTMLElement)) return
    const tag = node.tagName
    if (tag === 'BR') {
      chunks.push('\n')
      return
    }
    const isBlock = SANITIZE_HTML_BLOCK_TAGS.has(tag)
    if (isBlock && chunks.length && !chunks[chunks.length - 1]?.endsWith('\n')) chunks.push('\n')
    node.childNodes.forEach(walk)
    if (isBlock && !chunks[chunks.length - 1]?.endsWith('\n')) chunks.push('\n')
  }
  doc.body.childNodes.forEach(walk)
  return decodeHtmlEntities(chunks.join(' ').replace(/\s+\n/g, '\n').replace(/\n\s+/g, '\n').replace(/[ \t]{2,}/g, ' ').trim())
}

export const plainTextToHtml = (value: string) => {
  const normalized = value.replace(/\r\n/g, '\n').trim()
  if (!normalized) return ''
  return normalized
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, '<br>')}</p>`)
    .join('')
}

export const sanitizeComposerHtml = (html: string) => sanitizeHtml(html).replace(/&nbsp;/g, ' ')

const renderWhatsappInline = (value: string) =>
  escapeHtml(value)
    .replace(/```([\s\S]+?)```/g, (_, code: string) => `@@PRE@@${escapeHtml(code)}@@ENDPRE@@`)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*([^*\n]+)\*/g, '<strong>$1</strong>')
    .replace(/_([^_\n]+)_/g, '<em>$1</em>')
    .replace(/~([^~\n]+)~/g, '<del>$1</del>')
    .replace(/@@PRE@@([\s\S]+?)@@ENDPRE@@/g, '<pre><code>$1</code></pre>')

export const whatsappMarkupToHtml = (value: string) => {
  const normalized = value.replace(/\r\n/g, '\n').trim()
  if (!normalized) return ''
  const segments = normalized.split(/```([\s\S]*?)```/g)
  const htmlParts: string[] = []
  segments.forEach((segment, index) => {
    if (index % 2 === 1) {
      htmlParts.push(`<pre><code>${escapeHtml(segment)}</code></pre>`)
      return
    }
    segment
      .split(/\n{2,}/)
      .filter((paragraph) => paragraph.trim())
      .forEach((paragraph) => {
        htmlParts.push(`<p>${renderWhatsappInline(paragraph).replace(/\n/g, '<br>')}</p>`)
      })
  })
  return sanitizeHtml(htmlParts.join(''))
}

const wrapWhatsappToken = (token: string, text: string) => {
  const normalized = text.trim()
  return normalized ? `${token}${normalized}${token}` : normalized
}

const walkWhatsappNode = (node: Node): string => {
  if (node.nodeType === Node.TEXT_NODE) return (node.textContent || '').replace(/\u00a0/g, ' ')
  if (!(node instanceof HTMLElement)) return ''
  const children = Array.from(node.childNodes).map(walkWhatsappNode).join('')
  switch (node.tagName) {
    case 'BR':
      return '\n'
    case 'B':
    case 'STRONG':
      return wrapWhatsappToken('*', children)
    case 'EM':
    case 'I':
      return wrapWhatsappToken('_', children)
    case 'DEL':
    case 'S':
      return wrapWhatsappToken('~', children)
    case 'CODE':
      return node.parentElement?.tagName === 'PRE' ? children : wrapWhatsappToken('`', children)
    case 'PRE':
      return children.trim() ? `\n\n\`\`\`${children.trim()}\`\`\`\n\n` : ''
    case 'A': {
      const href = node.getAttribute('href')?.trim()
      const text = children.trim()
      if (!href) return text
      if (!text || text === href) return href
      return `${text} (${href})`
    }
    case 'LI':
      return `- ${children.trim()}\n`
    case 'UL':
    case 'OL':
      return `${children}\n`
    case 'P':
    case 'DIV':
    case 'BLOCKQUOTE':
    case 'SECTION':
    case 'ARTICLE':
      return children.trim() ? `${children.trim()}\n\n` : ''
    default:
      return children
  }
}

export const whatsappHtmlToMarkup = (html: string) => {
  const doc = new DOMParser().parseFromString(sanitizeComposerHtml(html), 'text/html')
  const value = Array.from(doc.body.childNodes).map(walkWhatsappNode).join('')
  return value
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export const hasComposerContent = (body: string, bodyHtml: string | null | undefined) =>
  Boolean(body.trim() || htmlToPlainText(bodyHtml || '').trim())
