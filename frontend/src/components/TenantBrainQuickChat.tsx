import { useEffect, useState } from 'react'
import { ToastCard, ToastStack } from './Toast'
import AiChatComposer from './AiChatComposer'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type MemoryQaMessage = { id: number; role: 'user' | 'assistant'; content: string; created_at: string }

type TenantBrainQuickChatProps = {
  tenantId?: number
}

type ResponseToast = {
  id: number
  message: string
  tone: 'success' | 'error' | 'info'
}

export default function TenantBrainQuickChat({ tenantId }: TenantBrainQuickChatProps) {
  const token = useAuthStore((state) => state.token)
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined

  const [messages, setMessages] = useState<MemoryQaMessage[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [fullscreen, setFullscreen] = useState(false)
  const [responseToast, setResponseToast] = useState<ResponseToast | null>(null)

  const loadHistory = async () => {
    if (!tenantId) return
    try {
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/memory-qa`, { headers: authHeaders })
      if (!response.ok) return
      const history = await response.json()
      setMessages(Array.isArray(history) ? history : [])
    } catch {
      // If history fails to load, the inline composer still works.
    }
  }

  useEffect(() => {
    setMessages([])
    setQuestion('')
    setError('')
    setFullscreen(false)
    setResponseToast(null)
    if (tenantId) void loadHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  useEffect(() => {
    if (!responseToast) return
    const timeoutId = window.setTimeout(() => setResponseToast(null), 8000)
    return () => window.clearTimeout(timeoutId)
  }, [responseToast])

  useEffect(() => {
    if (!fullscreen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fullscreen])

  const askQuestion = async () => {
    const prompt = question.trim()
    if (!tenantId || !prompt || sending) return
    try {
      setSending(true)
      setError('')
      setQuestion('')
      setMessages((current) => [...current, { id: -Date.now(), role: 'user', content: prompt, created_at: new Date().toISOString() }])
      const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/memory-qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ question: prompt }),
      })
      if (!response.ok) throw new Error('Failed to get an answer')
      const assistantMessage = (await response.json()) as MemoryQaMessage
      if (fullscreen) {
        await loadHistory()
      } else {
        setResponseToast({
          id: assistantMessage.id ?? Date.now(),
          message: assistantMessage.content,
          tone: 'info',
        })
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to get an answer'
      setError(message)
      if (!fullscreen) {
        setResponseToast({ id: Date.now(), message, tone: 'error' })
      }
    } finally {
      setSending(false)
    }
  }

  if (!tenantId) return null

  const previewMessages = messages.slice(-4)

  return (
    <>
      <div className="w-full min-w-0 rounded-2xl border border-brand-200 bg-white/90 px-3 py-2 shadow-sm backdrop-blur">
        {error ? <p className="mb-1.5 text-xs font-medium text-rose-500">{error}</p> : null}

        <AiChatComposer
          value={question}
          onChange={setQuestion}
          onSubmit={() => void askQuestion()}
          placeholder="Ask about this tenant..."
          disabled={sending}
          busy={sending}
          className="border-0 p-0 shadow-none"
          secondaryAction={(
            <button
              type="button"
              onClick={() => setFullscreen(true)}
              className="shrink-0 rounded-full border border-brand-100 bg-brand-50 px-3.5 py-2 text-xs font-semibold text-brand-700 transition hover:border-brand-200 hover:bg-brand-100"
            >
              Fullscreen
            </button>
          )}
        />
      </div>

      {!fullscreen && responseToast ? (
        <ToastStack>
          <ToastCard toastKey={responseToast.id} tone={responseToast.tone} durationMs={8000} className="w-full">
            <p className="font-medium">{responseToast.message}</p>
          </ToastCard>
        </ToastStack>
      ) : null}

      {fullscreen ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-gray-950/45 p-3 sm:p-6">
          <div className="flex h-[min(92vh,56rem)] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] border border-brand-200 bg-white shadow-2xl">
            <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-brand-700">Tenant Brain</p>
                <p className="text-xs text-gray-500">Fullscreen chat with this tenant's context loaded.</p>
              </div>
              <button
                type="button"
                onClick={() => setFullscreen(false)}
                className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs font-semibold text-gray-600 transition hover:border-gray-300 hover:bg-gray-50"
              >
                Exit fullscreen
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-auto bg-gradient-to-b from-brand-50/40 to-white px-4 py-4">
              <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-3">
                {previewMessages.length ? (
                  <div className="min-h-0 flex-1 space-y-2 overflow-auto rounded-2xl border border-gray-200 bg-white p-3">
                    {previewMessages.map((message) => (
                      <div
                        key={message.id}
                        className={`max-w-[90%] rounded-2xl px-3 py-2 text-sm ${
                          message.role === 'user' ? 'ml-auto bg-brand-600 text-white' : 'mr-auto bg-gray-50 text-gray-700'
                        }`}
                      >
                        <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] opacity-70">
                          {message.role === 'user' ? 'You' : 'AI'}
                        </p>
                        <p className="whitespace-pre-wrap leading-6">{message.content}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="min-h-0 flex-1 rounded-2xl border border-dashed border-brand-200 bg-white/70 p-6 text-sm text-gray-500">
                    No chat yet. Ask the tenant brain a question to start the conversation.
                  </div>
                )}

                {error ? <p className="text-xs font-medium text-rose-500">{error}</p> : null}

                <AiChatComposer
                  value={question}
                  onChange={setQuestion}
                  onSubmit={() => void askQuestion()}
                  placeholder="Ask about this tenant..."
                  disabled={sending}
                  busy={sending}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
