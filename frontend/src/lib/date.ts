const DISPLAY_DATE_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: '2-digit',
  month: 'long',
  year: 'numeric',
})

export function formatDisplayDate(value?: string | number | Date | null): string {
  if (value === null || value === undefined || value === '') return '-'

  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return '-'

  return DISPLAY_DATE_FORMATTER.format(date)
}
