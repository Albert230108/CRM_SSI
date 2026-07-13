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
