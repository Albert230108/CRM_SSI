import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type RedoQaContext = {
  what: string
  why: string | null
  instructions: string
  run_log_text: string
}

type RedoQaMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export default function RedoQaChat() {
  const token = useAuthStore((state) => state.token)
  const { redoLogId } = useParams()
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [context, setContext] = useState<RedoQaContext | null>(null)
  const [messages, setMessages] = useState<RedoQaMessage[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  useDocumentTitle(`CRM - Redo Q&A ${redoLogId ? `#${redoLogId}` : ''}`.trim())

  useEffect(() => {
    if (!redoLogId) {
      setStatus('error')
      setError('Redo request not found.')
      return
    }

    const controller = new AbortController()
    setStatus('loading')
    setError('')
    setHistoryError('')
    setContext(null)
    setMessages([])
    setQuestion('')

    const load = async () => {
      try {
        const contextResponse = await fetch(`${API_BASE_URL}/api/redo-requests/${redoLogId}/qa/context`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!contextResponse.ok) {
          if (contextResponse.status === 404) {
            throw new Error('Redo request not found.')
          }
          const data = await contextResponse.json().catch(() => null)
          throw new Error(data?.detail || 'Failed to load redo context')
        }
        const contextData: RedoQaContext = await contextResponse.json()
        setContext(contextData)

        const historyResponse = await fetch(`${API_BASE_URL}/api/redo-requests/${redoLogId}/qa`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (historyResponse.ok) {
          const history = await historyResponse.json()
          setMessages(Array.isArray(history) ? history : [])
        } else {
          setHistoryError('Prior Q&A history could not be loaded right now.')
        }

        setStatus('ready')
      } catch (err) {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Failed to load redo Q&A')
        setStatus('error')
      }
    }

    void load()
    return () => controller.abort()
  }, [authHeaders, redoLogId])

  const submitQuestion = async () => {
    const prompt = question.trim()
    if (!redoLogId || !prompt || sending) return

    const userMessage: RedoQaMessage = {
      id: -Date.now(),
      role: 'user',
      content: prompt,
      created_at: new Date().toISOString(),
    }

    try {
      setSending(true)
      setError('')
      setQuestion('')
      setMessages((current) => [...current, userMessage])

      const response = await fetch(`${API_BASE_URL}/api/redo-requests/${redoLogId}/qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ question: prompt }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail || 'Failed to get an answer')
      }

      setMessages((current) => [...current, data as RedoQaMessage])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get an answer')
    } finally {
      setSending(false)
    }
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void submitQuestion()
  }

  const renderMessage = (message: RedoQaMessage) => (
    <div
      key={message.id}
      className={`max-w-[92%] rounded-2xl px-3 py-2 text-sm shadow-sm ${
        message.role === 'user' ? 'ml-auto bg-cyan-600 text-white' : 'mr-auto border border-gray-200 bg-white text-gray-800'
      }`}
    >
      <p className={`mb-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${message.role === 'user' ? 'text-cyan-50/80' : 'text-gray-500'}`}>
        {message.role === 'user' ? 'You' : 'Assistant'}
      </p>
      <p className="whitespace-pre-wrap leading-6">{message.content}</p>
    </div>
  )

  return (
    <main className="flex h-screen flex-col overflow-hidden bg-[radial-gradient(circle_at_top,_rgba(8,145,178,0.12),_transparent_30%),linear-gradient(180deg,_#f8fafc_0%,_#eef8fb_100%)] text-gray-900">
      <header className="shrink-0 border-b border-cyan-100/70 bg-white/75 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-cyan-700">Redo QA</p>
            <h1 className="mt-1 text-lg font-semibold text-gray-900">Ask about a specific redo</h1>
            <p className="mt-1 text-sm text-gray-500">Full redo context on top, live Q&A below. This opens from the redo log and stays in its own tab.</p>
          </div>
          <div className="rounded-full border border-cyan-100 bg-cyan-50 px-3 py-1.5 text-xs font-semibold text-cyan-700">
            {redoLogId ? `Redo #${redoLogId}` : 'Redo'}
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden p-3 sm:p-4">
        <div className="mx-auto grid h-full max-w-6xl min-h-0 gap-3 lg:grid-cols-[1.08fr_0.92fr]">
          <section className="min-h-0 flex flex-col overflow-hidden rounded-[28px] border border-cyan-100 bg-white shadow-[0_18px_50px_rgba(15,23,42,0.08)]">
            <div className="border-b border-gray-100 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">Seed context</p>
              <p className="mt-1 text-sm text-gray-500">What changed, why it changed, the agent instructions, and the full untruncated run log.</p>
            </div>
            <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
              {status === 'loading' ? <p className="text-sm text-gray-500">Loading redo context...</p> : null}
              {status === 'error' ? <p className="text-sm text-rose-600">{error}</p> : null}
              {status === 'ready' && context ? (
                <div className="space-y-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-gray-500">What to change</p>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-gray-800">{context.what}</p>
                    </div>
                    <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-gray-500">Why</p>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-gray-800">{context.why || 'Not provided.'}</p>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-cyan-100 bg-cyan-50/50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">Your instructions</p>
                    <pre className="mt-1 whitespace-pre-wrap rounded-xl border border-cyan-100 bg-white p-3 text-sm leading-6 text-gray-800">{context.instructions || 'No memory_redo instructions are configured for this profile.'}</pre>
                  </div>

                  <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-gray-500">Full run log</p>
                    <pre className="mt-1 whitespace-pre-wrap rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm leading-6 text-gray-800">{context.run_log_text || 'No linked AI agent run.'}</pre>
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section className="min-h-0 flex flex-col overflow-hidden rounded-[28px] border border-gray-200 bg-white shadow-[0_18px_50px_rgba(15,23,42,0.08)]">
            <div className="border-b border-gray-100 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">Conversation</p>
              <p className="mt-1 text-sm text-gray-500">Ask follow-up questions about the redo event and keep the conversation grounded in the original run.</p>
            </div>

            <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
              {messages.length ? (
                <div className="space-y-2">
                  {messages.map(renderMessage)}
                </div>
              ) : (
                <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-cyan-200 bg-cyan-50/30 px-6 py-10 text-sm text-gray-500">
                  No questions yet. Ask about the redo, the run log, or the agent instructions to start the thread.
                </div>
              )}
            </div>

            <div className="border-t border-gray-100 px-4 py-3">
              {historyError ? <p className="mb-2 text-xs font-medium text-amber-700">{historyError}</p> : null}
              {error && status !== 'error' ? <p className="mb-2 text-xs font-medium text-rose-600">{error}</p> : null}
              <form className="flex flex-col gap-2 sm:flex-row" onSubmit={submit}>
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask a question about this redo..."
                  disabled={sending || status !== 'ready'}
                  rows={3}
                  className="min-h-24 min-w-0 flex-1 resize-none rounded-2xl border border-cyan-100 bg-cyan-50/40 px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-400 focus:border-cyan-300 focus:bg-white disabled:cursor-not-allowed"
                />
                <div className="flex shrink-0 flex-row gap-2 sm:flex-col">
                  <button
                    type="submit"
                    disabled={!question.trim() || sending || status !== 'ready'}
                    className="rounded-2xl border border-cyan-200 bg-cyan-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {sending ? 'Sending...' : 'Ask'}
                  </button>
                </div>
              </form>
            </div>
          </section>
        </div>
      </div>
    </main>
  )
}
