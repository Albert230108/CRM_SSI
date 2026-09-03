import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import AiChatComposer from '../components/AiChatComposer'
import InlineSpinner from '../components/InlineSpinner'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type RunQaContext = {
  run_summary: string
  instructions: string
  qa_preamble: string
  model: string
  temperature: number | null
  max_output_tokens: number | null
  run_log_text: string
}

type RunQaMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export default function RunQaChat() {
  const token = useAuthStore((state) => state.token)
  const { runId } = useParams()
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [historyError, setHistoryError] = useState('')
  const [context, setContext] = useState<RunQaContext | null>(null)
  const [messages, setMessages] = useState<RunQaMessage[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  useDocumentTitle(`CRM - Run Q&A ${runId ? `#${runId}` : ''}`.trim())

  useEffect(() => {
    if (!runId) {
      setStatus('error')
      setError('Agent run not found.')
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
        const contextResponse = await fetch(`${API_BASE_URL}/api/ai-agent-runs/${runId}/qa/context`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!contextResponse.ok) {
          if (contextResponse.status === 404) {
            throw new Error('Agent run not found.')
          }
          const data = await contextResponse.json().catch(() => null)
          throw new Error(data?.detail || 'Failed to load run context')
        }
        const contextData: RunQaContext = await contextResponse.json()
        setContext(contextData)

        const historyResponse = await fetch(`${API_BASE_URL}/api/ai-agent-runs/${runId}/qa`, {
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
        setError(err instanceof Error ? err.message : 'Failed to load run Q&A')
        setStatus('error')
      }
    }

    void load()
    return () => controller.abort()
  }, [authHeaders, runId])

  const submitQuestion = async () => {
    const prompt = question.trim()
    if (!runId || !prompt || sending) return

    const userMessage: RunQaMessage = {
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

      const response = await fetch(`${API_BASE_URL}/api/ai-agent-runs/${runId}/qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ question: prompt }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail || 'Failed to get an answer')
      }

      setMessages((current) => [...current, data as RunQaMessage])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get an answer')
    } finally {
      setSending(false)
    }
  }

  const renderMessage = (message: RunQaMessage) => (
    <div
      key={message.id}
      className={`max-w-[92%] rounded-2xl px-3 py-2 text-sm shadow-sm ${
        message.role === 'user' ? 'ml-auto bg-brand-600 text-white' : 'mr-auto border border-gray-200 bg-white text-gray-800'
      }`}
    >
      <p className={`mb-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${message.role === 'user' ? 'text-brand-50/80' : 'text-gray-500'}`}>
        {message.role === 'user' ? 'You' : 'Assistant'}
      </p>
      <p className="whitespace-pre-wrap leading-6">{message.content}</p>
    </div>
  )

  return (
    <main className="flex h-screen animate-fade-in flex-col overflow-hidden bg-[radial-gradient(circle_at_top,_rgba(8,145,178,0.12),_transparent_30%),linear-gradient(180deg,_#f8fafc_0%,_#eef8fb_100%)] text-gray-900">
      <header className="shrink-0 border-b border-brand-100/70 bg-white/75 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-brand-700">Run QA</p>
            <h1 className="mt-1 text-lg font-semibold text-gray-900">Ask about a specific agent run</h1>
            <p className="mt-1 text-sm text-gray-500">Full run log on top, live Q&A below. Works for planner, brain-writer, and action-writer runs. This opens from the runs log and stays in its own tab.</p>
          </div>
          <div className="rounded-full border border-brand-100 bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700">
            {runId ? `Run #${runId}` : 'Run'}
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden p-3 sm:p-4">
        <div className="mx-auto grid h-full max-w-6xl min-h-0 gap-3 lg:grid-cols-[1.08fr_0.92fr]">
          <section className="min-h-0 flex flex-col overflow-hidden rounded-[28px] border border-brand-100 bg-white shadow-[0_18px_50px_rgba(15,23,42,0.08)]">
            <div className="border-b border-gray-100 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand-700">Seed context</p>
              <p className="mt-1 text-sm text-gray-500">The run summary, the agent instructions, and the full untruncated run log.</p>
            </div>
            <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
              {status === 'loading' ? <p className="flex items-center gap-2 text-sm text-gray-500"><InlineSpinner size="sm" /> Loading run context…</p> : null}
              {status === 'error' ? <p className="text-sm text-rose-600">{error}</p> : null}
              {status === 'ready' && context ? (
                <div className="space-y-3">
                  <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-gray-500">Run summary</p>
                    <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-gray-800">{context.run_summary}</p>
                  </div>

                  <div className="rounded-2xl border border-brand-100 bg-brand-50/50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand-700">Your instructions</p>
                    <pre className="mt-1 whitespace-pre-wrap rounded-xl border border-brand-100 bg-white p-3 text-sm leading-6 text-gray-800">{context.instructions || 'No run_qa instructions are configured for this profile.'}</pre>
                  </div>

                  <div className="rounded-2xl border border-brand-100 bg-brand-50/50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand-700">Role preamble</p>
                    <pre className="mt-1 whitespace-pre-wrap rounded-xl border border-brand-100 bg-white p-3 text-sm leading-6 text-gray-800">{context.qa_preamble || 'No run QA preamble is configured for this profile.'}</pre>
                  </div>

                  <div className="rounded-2xl border border-brand-100 bg-brand-50/50 p-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand-700">Model &amp; sampling</p>
                    <p className="mt-1 whitespace-pre-wrap rounded-xl border border-brand-100 bg-white p-3 text-sm leading-6 text-gray-800">{`Model: ${context.model} · Temperature: ${context.temperature === null ? 'Default' : context.temperature} · Max output tokens: ${context.max_output_tokens === null ? 'Default' : context.max_output_tokens}`}</p>
                  </div>

                  <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-gray-500">Full run log</p>
                    <pre className="mt-1 whitespace-pre-wrap rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm leading-6 text-gray-800">{context.run_log_text || 'This run has no recorded steps.'}</pre>
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section className="min-h-0 flex flex-col overflow-hidden rounded-[28px] border border-gray-200 bg-white shadow-[0_18px_50px_rgba(15,23,42,0.08)]">
            <div className="border-b border-gray-100 px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-brand-700">Conversation</p>
              <p className="mt-1 text-sm text-gray-500">Ask follow-up questions about what this run did and keep the conversation grounded in its log.</p>
            </div>

            <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
              {messages.length ? (
                <div className="space-y-2">
                  {messages.map(renderMessage)}
                </div>
              ) : (
                <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-brand-200 bg-brand-50/30 px-6 py-10 text-sm text-gray-500">
                  No questions yet. Ask about the run log, a specific step, or the agent instructions to start the thread.
                </div>
              )}
            </div>

            <div className="border-t border-gray-100 px-4 py-3">
              {historyError ? <p className="mb-2 text-xs font-medium text-amber-700">{historyError}</p> : null}
              {error && status !== 'error' ? <p className="mb-2 text-xs font-medium text-rose-600">{error}</p> : null}
              <AiChatComposer
                value={question}
                onChange={setQuestion}
                onSubmit={() => void submitQuestion()}
                placeholder="Ask a question about this run..."
                disabled={sending || status !== 'ready'}
                busy={sending}
                multiline
              />
            </div>
          </section>
        </div>
      </div>
    </main>
  )
}
