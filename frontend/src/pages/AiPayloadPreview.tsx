import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type PreviewRequest = {
  tenantId: number
  channel: string
  templateId: number | null
  roughDraft: string | null
}

type PreviewResponse = {
  payload: string
  char_count: number
  approx_token_count: number
  template_id: number
}

export default function AiPayloadPreview() {
  const token = useAuthStore((state) => state.token)
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading')
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const previewId = params.get('id')
    const storageKey = previewId ? `ai-payload-preview:${previewId}` : null
    const raw = storageKey ? window.localStorage.getItem(storageKey) : null
    if (storageKey) window.localStorage.removeItem(storageKey)

    if (!raw) {
      setStatus('error')
      setError('No pending preview request found. Reopen this tab from "Draft with AI".')
      return
    }

    let request: PreviewRequest
    try {
      request = JSON.parse(raw)
    } catch {
      setStatus('error')
      setError('Could not read the preview request.')
      return
    }

    const load = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/communications/tenants/${request.tenantId}/ai-draft/preview`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            channel: request.channel,
            template_id: request.templateId,
            rough_draft: request.roughDraft,
          }),
        })
        if (!response.ok) {
          const data = await response.json().catch(() => null)
          throw new Error(data?.detail || 'Failed to load AI payload preview')
        }
        const data: PreviewResponse = await response.json()
        setPreview(data)
        setStatus('ready')
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load AI payload preview')
        setStatus('error')
      }
    }
    load()
  }, [token])

  const handleCopy = async () => {
    if (!preview) return
    await navigator.clipboard.writeText(preview.payload)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-4">
      <h1 className="text-lg font-semibold text-gray-900">Exact AI Payload Preview</h1>
      <p className="mt-1 text-sm text-gray-500">
        This is exactly the text that will be sent to Gemini if you click "Draft with AI" now, in the fixed order:
        0. Goal &amp; Guidelines, 1. Template text, 1b. Knowledge base (brain sections), 2. Message history,
        3. Beds24 info, 4. Your typed reply.
      </p>

      {status === 'loading' ? <p className="mt-4 text-sm text-gray-500">Loading...</p> : null}
      {status === 'error' ? <p className="mt-4 text-sm text-rose-600">{error}</p> : null}

      {status === 'ready' && preview ? (
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-gray-600">
            <span className="rounded-full bg-gray-100 px-2 py-0.5">{preview.char_count} characters</span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5">~{preview.approx_token_count} tokens (approx.)</span>
            <button
              type="button"
              onClick={handleCopy}
              className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50"
            >
              {copied ? 'Copied!' : 'Copy to clipboard'}
            </button>
          </div>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-900">
            {preview.payload}
          </pre>
        </div>
      ) : null}
    </main>
  )
}
