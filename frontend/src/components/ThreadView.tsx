import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

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
      setError('Select a tenant to view the conversation.')
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
    <div className="flex h-full min-h-[680px] flex-col rounded-2xl border border-slate-800 bg-slate-950/80">
      <div className="border-b border-slate-800 px-5 py-4">
        <p className="text-xs uppercase tracking-[0.35em] text-cyan-400">Thread view</p>
        <h2 className="mt-1 text-xl font-semibold text-white">{tenant ? tenant.name : 'No tenant selected'}</h2>
        <p className="mt-1 text-sm text-slate-400">
          {tenant ? [tenant.email || 'No email on file', tenant.phone || 'No phone on file'].join(' · ') : 'Pick a tenant from the left pane.'}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {loading ? <p className="text-sm text-slate-400">Loading conversation...</p> : null}
        {error ? <p className="mb-4 text-sm text-rose-400">{error}</p> : null}

        <div className="space-y-4">
          {sortedItems.map((item) => {
            const isEmail = item.channel === 'email'
            return (
              <article key={item.id} className={`max-w-[85%] rounded-2xl border px-4 py-3 ${isEmail ? 'ml-0 border-amber-500/30 bg-amber-500/10' : 'ml-auto border-cyan-500/30 bg-cyan-500/10'}`}>
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-slate-400">
                  <span className={`rounded-full px-2 py-1 font-semibold ${isEmail ? 'bg-amber-400/20 text-amber-200' : 'bg-cyan-400/20 text-cyan-200'}`}>
                    {isEmail ? 'Email' : 'WhatsApp'}
                  </span>
                  <span>{new Date(item.created_at).toLocaleString()}</span>
                </div>
                {item.subject ? <p className="mt-2 text-sm font-semibold text-white">{item.subject}</p> : null}
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-200">{item.message}</p>
              </article>
            )
          })}
          {!sortedItems.length && !loading ? <p className="text-sm text-slate-500">No messages yet.</p> : null}
        </div>
      </div>

      <form onSubmit={handleSend} className="border-t border-slate-800 p-4">
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setChannel('whatsapp')} className={`rounded-full px-3 py-1.5 text-sm font-semibold ${channel === 'whatsapp' ? 'bg-cyan-500 text-slate-950' : 'bg-slate-800 text-slate-300'}`}>
            WhatsApp
          </button>
          <button type="button" onClick={() => setChannel('email')} className={`rounded-full px-3 py-1.5 text-sm font-semibold ${channel === 'email' ? 'bg-amber-400 text-slate-950' : 'bg-slate-800 text-slate-300'}`}>
            Email reply
          </button>
        </div>

        {channel === 'email' ? (
          <input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="Subject"
            className="mt-3 w-full rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500"
          />
        ) : null}

        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={4}
          placeholder={channel === 'whatsapp' ? 'Write a WhatsApp message...' : 'Write an email reply...'}
          className="mt-3 w-full resize-none rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500"
        />

        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            {channel === 'whatsapp' ? 'Sends through the WhatsApp backend integration.' : 'Stores and sends as an email-thread reply.'}
          </p>
          <button type="submit" disabled={sending || !tenantId || !message.trim()} className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 transition disabled:cursor-not-allowed disabled:opacity-50">
            {sending ? 'Sending...' : 'Send'}
          </button>
        </div>
      </form>
    </div>
  )
}
