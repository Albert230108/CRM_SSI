export function getChannelIcon(channel: string | null | undefined) {
  if (!channel) return null
  if (channel.toLowerCase().includes('email')) return '✉️'
  if (channel.toLowerCase().includes('whatsapp')) return '💬'
  return '💬'
}

export function formatRelativeTime(dateStr: string | null | undefined) {
  if (!dateStr) return null
  try {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return null
  }
}
