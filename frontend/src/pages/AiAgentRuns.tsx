import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { getAiSettingsReturnHref } from '../lib/aiSettingsNavigation'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type AgentRun = {
  id: number
  tenant_id: number
  tenant_name: string | null
  channel: string
  mode: string
  status: string
  escalation_reason: string | null
  final_template_id: number | null
  final_template_name: string | null
  checker_feedback: string | null
  attempts: number
  total_prompt_tokens: number
  total_output_tokens: number
  duration_ms: number
  created_at: string
}

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-emerald-50 text-emerald-700',
  needs_review: 'bg-amber-50 text-amber-700',
  escalated: 'bg-orange-50 text-orange-700',
  skipped: 'bg-gray-100 text-gray-600',
  failed: 'bg-rose-50 text-rose-700',
}

const STATUS_FILTERS = ['', 'completed', 'needs_review', 'escalated', 'skipped', 'failed']

function templateLabel(id: number | null, name?: string | null): string {
  if (name) return name
  if (id != null) return `Template #${id} (deleted)`
  return '—'
}

export default function AiAgentRuns() {
  useDocumentTitle('CRM - AI Runs')
  const token = useAuthStore((state) => state.token)
  const location = useLocation()
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  useEffect(() => {
    const controller = new AbortController()

    const load = async () => {
      try {
        setLoading(true)
        const query = statusFilter ? `?status=${statusFilter}` : ''
        const response = await fetch(`${API_BASE_URL}/api/ai-agent-runs${query}`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error('Failed to load runs')
        }
        setRuns(await response.json())
      } catch (err) {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Failed to load runs')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    setError('')
    void load()
    return () => controller.abort()
  }, [authHeaders, statusFilter])

  return (
    <main className="mx-auto max-w-6xl px-6 py-4">
      <Link to={getAiSettingsReturnHref(location.search, '/settings')} className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
      <h1 className="mt-1.5 text-2xl font-semibold text-gray-900">AI Planner Runs</h1>
      <p className="mt-1.5 text-sm text-gray-500">
        Every planner &rarr; drafter &rarr; checker execution, with the exact prompts and responses, the template that
        was chosen and why, and what it cost.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((value) => (
          <button
            key={value || 'all'}
            type="button"
            onClick={() => setStatusFilter(value)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
              statusFilter === value ? 'bg-indigo-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            {value ? value.replace('_', ' ') : 'all'}
          </button>
        ))}
      </div>

      {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}

      <section className="mt-3 rounded-2xl border border-gray-200 bg-white p-3.5">
        {loading ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : runs.length === 0 ? (
          <p className="text-sm text-gray-500">No runs recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-[0.12em] text-gray-500">
                  <th className="py-1.5 pr-3">When</th>
                  <th className="py-1.5 pr-3">Tenant</th>
                  <th className="py-1.5 pr-3">Channel</th>
                  <th className="py-1.5 pr-3">Mode</th>
                  <th className="py-1.5 pr-3">Status</th>
                  <th className="py-1.5 pr-3">Template</th>
                  <th className="py-1.5 pr-3">Tries</th>
                  <th className="py-1.5 pr-3">Tokens</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-t border-gray-100">
                    <td className="py-1.5 pr-3 text-gray-600">{new Date(run.created_at).toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-gray-900">{run.tenant_name ?? `#${run.tenant_id}`}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{run.channel}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{run.mode}</td>
                    <td className="py-1.5 pr-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_STYLES[run.status] ?? 'bg-gray-100 text-gray-600'}`}>
                        {run.status.replace('_', ' ')}
                      </span>
                      {run.escalation_reason ? (
                        <span className="ml-2 text-xs text-gray-500">{run.escalation_reason}</span>
                      ) : null}
                    </td>
                    <td className="py-1.5 pr-3 text-gray-600">{templateLabel(run.final_template_id, run.final_template_name)}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{run.attempts}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{run.total_prompt_tokens + run.total_output_tokens}</td>
                    <td className="py-1.5">
                      <button
                        type="button"
                        onClick={() => window.open(`/ai-runs/${run.id}`, '_blank')}
                        className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700"
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  )
}
