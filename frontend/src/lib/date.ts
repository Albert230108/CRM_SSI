const DISPLAY_WEEKDAY_FORMATTER = new Intl.DateTimeFormat('en-GB', { weekday: 'short' })
const DISPLAY_DAY_MONTH_YEAR_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'long',
  year: 'numeric',
})
const DISPLAY_TIME_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

function toValidDate(value?: string | number | Date | null): Date | null {
  if (value === null || value === undefined || value === '') return null
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date
}

export function formatDisplayDate(value?: string | number | Date | null): string {
  const date = toValidDate(value)
  if (!date) return '-'

  return `${DISPLAY_WEEKDAY_FORMATTER.format(date)} ${DISPLAY_DAY_MONTH_YEAR_FORMATTER.format(date)}`
}

export function formatDisplayTime(value?: string | number | Date | null): string {
  const date = toValidDate(value)
  if (!date) return '-'

  return DISPLAY_TIME_FORMATTER.format(date)
}

export function formatDisplayDateTime(value?: string | number | Date | null): string {
  const date = toValidDate(value)
  if (!date) return '-'

  return `${formatDisplayDate(date)}, ${formatDisplayTime(date)}`
}

const MINUTE_MS = 60_000
const HOUR_MS = 60 * MINUTE_MS
const DAY_MS = 24 * HOUR_MS

/** Renders "Xd ago" / "Xh ago" / "Xmin ago" using the single largest applicable unit; omits a unit entirely rather than showing it as zero. Falls back to the absolute date/time for future timestamps. */
export function formatRelativeDateTime(value?: string | number | Date | null, now: Date = new Date()): string {
  const date = toValidDate(value)
  if (!date) return '-'

  const diffMs = now.getTime() - date.getTime()
  if (diffMs < 0) return formatDisplayDateTime(date)
  if (diffMs < MINUTE_MS) return 'Just now'
  if (diffMs < HOUR_MS) return `${Math.floor(diffMs / MINUTE_MS)}min ago`
  if (diffMs < DAY_MS) return `${Math.floor(diffMs / HOUR_MS)}h ago`

  const days = Math.floor(diffMs / DAY_MS)
  return `${days} day${days === 1 ? '' : 's'} ago`
}
