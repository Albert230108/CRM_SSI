import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Modal from './ui/Modal'
import Input from './ui/Input'
import Badge from './ui/Badge'
import InlineSpinner from './InlineSpinner'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type SearchResult = {
  type: string
  id: number
  tenant_id: number | null
  title: string
  snippet: string
}

// Human labels for the filter chips + result badges, in a stable display order.
const TYPE_LABELS: Record<string, string> = {
  tenant: 'Tenants',
  communication: 'Messages',
  email_message: 'Emails',
  conversation: 'Conversations',
  brain_section: 'AI Brain',
  tenant_brain_entry: 'Brain notes',
  tenant_brain_field: 'Brain fields',
  working_memory_rule: 'Rules',
  action_item: 'Actions',
  finance: 'Finance',
  reply_draft: 'Drafts',
  ai_template: 'Templates',
}

const labelFor = (type: string) => TYPE_LABELS[type] ?? type

/** Where a result links to when clicked. */
function resultPath(result: SearchResult): string {
  switch (result.type) {
    case 'brain_section':
      return '/settings/brain'
    case 'working_memory_rule':
      return '/working-memory'
    case 'ai_template':
      return `/settings/ai-templates/${result.id}`
    default:
      // Everything else is (or can be) tied to a tenant: open the tenant dashboard when we
      // know which tenant, otherwise fall back to the relevant list page.
      if (result.tenant_id != null) return `/dashboard/tenant/${result.tenant_id}`
      if (result.type === 'action_item') return '/actions'
      return '/'
  }
}

type GlobalSearchModalProps = {
  open: boolean
  onClose: () => void
}

export default function GlobalSearchModal({ open, onClose }: GlobalSearchModalProps) {
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeType, setActiveType] = useState<string | null>(null)

  // Reset transient state whenever the overlay is opened, and focus the input.
  useEffect(() => {
    if (!open) return
    setQuery('')
    setResults([])
    setError('')
    setActiveType(null)
    const frame = requestAnimationFrame(() => inputRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [open])

  // Debounced backend search with stale-request cancellation (mirrors TenantList).
  useEffect(() => {
    if (!open) return
    const trimmed = query.trim()
    if (!trimmed) {
      setResults([])
      setLoading(false)
      setError('')
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        setLoading(true)
        setError('')
        const response = await fetch(
          `${API_BASE_URL}/api/search?q=${encodeURIComponent(trimmed)}`,
          {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          },
        )
        if (!response.ok) throw new Error('Search failed')
        setResults(await response.json())
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Search failed')
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [query, open, token])

  // Counts per type drive the chip labels; only types with hits get a chip.
  const counts = useMemo(() => {
    const map = new Map<string, number>()
    for (const r of results) map.set(r.type, (map.get(r.type) ?? 0) + 1)
    return map
  }, [results])

  const orderedTypes = useMemo(
    () => Object.keys(TYPE_LABELS).filter((t) => counts.has(t)),
    [counts],
  )

  const visibleResults = activeType ? results.filter((r) => r.type === activeType) : results

  const openResult = (result: SearchResult) => {
    navigate(resultPath(result))
    onClose()
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      ariaLabel="Global search"
      className="w-full max-w-2xl self-start mt-[10vh]"
    >
      <div className="flex max-h-[80vh] flex-col overflow-hidden rounded-3xl border border-gray-200 bg-white shadow-xl">
        <div className="border-b border-gray-100 p-4">
          <Input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tenants, messages, brain, finance…"
            aria-label="Search everything"
          />
          {orderedTypes.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setActiveType(null)}
                className={`rounded-full px-2 py-0.5 text-xs font-semibold transition ${
                  activeType === null ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                All ({results.length})
              </button>
              {orderedTypes.map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setActiveType((current) => (current === type ? null : type))}
                  className={`rounded-full px-2 py-0.5 text-xs font-semibold transition ${
                    activeType === type ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  {labelFor(type)} ({counts.get(type)})
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {loading ? (
            <p className="flex items-center gap-2 p-3 text-sm text-gray-500">
              <InlineSpinner size="sm" /> Searching…
            </p>
          ) : error ? (
            <p className="p-3 text-sm text-rose-500">{error}</p>
          ) : !query.trim() ? (
            <p className="p-3 text-sm text-gray-500">
              Type to search across everything in the CRM. Press <kbd>Esc</kbd> to close.
            </p>
          ) : visibleResults.length === 0 ? (
            <p className="p-3 text-sm text-gray-500">No matches.</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {visibleResults.map((result) => (
                <li key={`${result.type}-${result.id}`}>
                  <button
                    type="button"
                    onClick={() => openResult(result)}
                    className="flex w-full items-start gap-3 rounded-xl px-3 py-2 text-left transition hover:bg-gray-50"
                  >
                    <Badge tone="gray" className="mt-0.5 shrink-0">
                      {labelFor(result.type)}
                    </Badge>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-gray-900">
                        {result.title}
                      </span>
                      {result.snippet ? (
                        <span className="block truncate text-xs text-gray-500">{result.snippet}</span>
                      ) : null}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  )
}
