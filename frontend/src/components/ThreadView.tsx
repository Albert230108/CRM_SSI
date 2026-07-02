import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useAuthStore } from '../store/authStore'
import { formatDisplayDate } from '../lib/date'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type Communication = {
  id: number
  tenant_id: number
  channel: 'email' | 'whatsapp' | string
  subject: string | null
  message: string
  created_at: string
}

type TenantSummary = {
  id: number
  name: string
  email: string | null
  phone: string | null
}

type ThreadViewProps = {
  tenantId?: number
}

export default function ThreadView({ tenantId }: ThreadViewProps) {
  const token = useAuthStore((state) => state.token)
  const [tenant, setTenant] = useState<TenantSummary | null>(null)
  const [items, setItems] = useState<Communication[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [channel, setChannel] = useState<'whatsapp' | 'email'>('whatsapp')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)

  useEffect(() => {
    if (!tenantId) {
      setTenant(null)
      setItems([])
      setError('Select a tenant')
      return
    }

    const controller = new AbortController()

    const loadThread = async () => {
      try {
        setLoading(true)
        setError('')
        const [tenantResponse, timelineResponse] = await Promise.all([
          fetch(`${API_BASE_URL}/api/tenants/${tenantId}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
          fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/timeline`, {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
            signal: controller.signal,
          }),
        ])

        if (!tenantResponse.ok || !timelineResponse.ok) {
          throw new Error('Failed to load thread')
        }

        const tenantData: TenantSummary = await tenantResponse.json()
        const timelineData: Communication[] = await timelineResponse.json()
        setTenant(tenantData)
        setItems(timelineData)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load thread')
      } finally {
        setLoading(false)
      }
    }

    loadThread()
    return () => controller.abort()
  }, [tenantId, token])

  const sortedItems = useMemo(() => [...items].sort((left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime()), [items])

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!tenantId || !message.trim()) return

    try {
      setSending(true)
      setError('')
      const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${tenantId}/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ channel, subject: subject.trim() || null, message }),
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || 'Failed to send message')
      }

      const saved: Communication = await response.json()
      setItems((current) => [...current, saved])
      setMessage('')
      if (channel === 'email') {
        setSubject('')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex h-full min-h-[680px] flex-col rounded-2xl border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-200 px-5 py-4">
        <h2 className="text-xl font-semibold text-gray-900">{tenant ? tenant.name : 'Messages'}</h2>
        <p className="mt-1 text-sm text-gray-500">
          {tenant ? [tenant.email || 'No email on file', tenant.phone || 'No phone on file'].join(' ? ') : 'Select a tenant'}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {loading ? <p className="text-sm text-gray-500">Loading...</p> : null}
        {error ? <p className="mb-4 text-sm text-rose-400">{error}</p> : null}

        <div className="space-y-4">
          {sortedItems.map((item) => {
            const isEmail = item.channel === 'email'
            return (
              <article key={item.id} className={`max-w-[85%] rounded-2xl border px-4 py-3 ${isEmail ? 'ml-0 border-amber-200 bg-amber-50' : 'ml-auto border-cyan-200 bg-cyan-50'}`}>
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-gray-500">
                  <span className={`rounded-full px-2 py-1 font-semibold ${isEmail ? 'bg-amber-100 text-amber-700' : 'bg-cyan-100 text-cyan-700'}`}>
                    {isEmail ? 'Email' : 'WhatsApp'}
                  </span>
                  <span>{formatDisplayDate(item.created_at)}</span>
                </div>
                {item.subject ? <p className="mt-2 text-sm font-semibold text-gray-900">{item.subject}</p> : null}
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-700">{item.message}</p>
              </article>
            )
          })}
          {!sortedItems.length && !loading ? <p className="text-sm text-gray-500">No messages</p> : null}
        </div>
      </div>

      <form onSubmit={handleSend} className="border-t border-gray-200 p-4">
        <div className="flex w-full gap-2">
          <button type="button" onClick={() => setChannel('whatsapp')} className={`flex-1 rounded-full px-3 py-1.5 text-center text-sm font-semibold ${channel === 'whatsapp' ? 'bg-cyan-600 text-white' : 'bg-gray-100 text-gray-700'}`}>
            WhatsApp
          </button>
          <button type="button" onClick={() => setChannel('email')} className={`flex-1 rounded-full px-3 py-1.5 text-center text-sm font-semibold ${channel === 'email' ? 'bg-cyan-600 text-white' : 'bg-gray-100 text-gray-700'}`}>
            Email
          </button>
        </div>

        {channel === 'email' ? (
          <input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="Subject"
            className="mt-3 w-full rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
          />
        ) : null}

        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={4}
          placeholder={channel === 'whatsapp' ? 'Write a WhatsApp message...' : 'Write an email...'}
          className="mt-3 w-full resize-none rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
        />

        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-gray-500">
            {channel === 'whatsapp' ? 'WhatsApp send.' : 'Email reply.'}
          </p>
          <button type="submit" disabled={sending || !tenantId || !message.trim()} className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-50">
            {sending ? 'Sending...' : 'Send'}
          </button>
        </div>
      </form>
    </div>
  )
}
