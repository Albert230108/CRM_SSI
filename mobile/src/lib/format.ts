/** Small display helpers shared across screens. */

/** Initials from a name, for list avatars. e.g. "Jane Doe" -> "JD". */
export function initials(name: string | null | undefined): string {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p.charAt(0).toUpperCase()).join('') || '?'
}

/** Compact relative-ish timestamp for lists: time today, "Mon", or a short date. */
export function formatListTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  if (sameDay) {
    return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  }
  const diffDays = (now.getTime() - date.getTime()) / 86_400_000
  if (diffDays < 7) {
    return date.toLocaleDateString(undefined, { weekday: 'short' })
  }
  return date.toLocaleDateString(undefined, { day: '2-digit', month: 'short' })
}

/** Full-ish timestamp for message bubbles. */
export function formatBubbleTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Collapse whitespace and trim a preview string to a single tidy line. */
export function oneLine(text: string | null | undefined, max = 120): string {
  if (!text) return ''
  const collapsed = text.replace(/\s+/g, ' ').trim()
  return collapsed.length > max ? `${collapsed.slice(0, max - 1)}…` : collapsed
}

/** Short calendar date (no time) for booking dates / due dates. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

/**
 * Format a money amount for display. Amounts arrive as strings from the finance endpoint (to avoid
 * float drift); we parse leniently and fall back to the raw string if it isn't numeric.
 */
export function formatMoney(amount: string | number, currency?: string | null): string {
  const n = typeof amount === 'number' ? amount : Number(amount)
  if (Number.isNaN(n)) return String(amount)
  const formatted = n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency ? `${currency} ${formatted}` : formatted
}
