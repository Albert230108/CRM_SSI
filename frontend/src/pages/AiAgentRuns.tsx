import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

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
  checker_feedback: string | null
  attempts: number
  total_prompt_tokens: number
  total_output_tokens: number
  duration_ms: number
  created_at: string
}

type AgentRunStep = {
  id: number
  step_index: number
  stage: string
  model: string | null
  prompt: string | null
  response: string | null
  parsed: Record<string, unknown> | null
  prompt_tokens: number | null
  output_tokens: number | null
  latency_ms: number | null
  error: string | null
}

type AgentRunDetail = AgentRun & { final_text: string | null; steps: AgentRunStep[] }

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-emerald-50 text-emerald-700',
  needs_review: 'bg-amber-50 text-amber-700',
  escalated: 'bg-orange-50 text-orange-700',
  skipped: 'bg-gray-100 text-gray-600',
  failed: 'bg-rose-50 text-rose-700',
}

const STATUS_FILTERS = ['', 'completed', 'needs_review', 'escalated', 'skipped', 'failed']

export default function AiAgentRuns() {
  const token = useAuthStore((state) => state.token)
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [selected, setSelected] = useState<AgentRunDetail | null>(null)
  const [expandedStepId, setExpandedStepId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  const load = useCallback(async () => {
    const query = statusFilter ? `?status=${statusFilter}` : ''
    const response = await fetch(`${API_BASE_URL}/api/ai-agent-runs${query}`, { headers: authHeaders })
    if (!response.ok) {
      setError('Failed to load runs')
      setLoading(false)
      return
    }
    setRuns(await response.json())
    setLoading(false)
  }, [authHeaders, statusFilter])

  useEffect(() => {
    void load()
  }, [load])

  const openRun = async (runId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/ai-agent-runs/${runId}`, { headers: authHeaders })
    if (!response.ok) {
      setError('Failed to load the run')
      return
    }
    setSelected(await response.json())
    setExpandedStepId(null)
  }

  const plannerStep = selected?.steps.find((step) => step.stage === 'planner')
  const plan = (plannerStep?.parsed ?? null) as
    | { reasoning?: string; confidence?: number; extra_instructions?: string; extra_brain_sections?: string[]; alternatives?: { template_id: number; why_not: string }[] }
    | null

  return (
    <main className="mx-auto max-w-6xl px-6 py-4">
      <Link to="/settings" className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
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
                    <td className="py-1.5 pr-3 text-gray-600">{run.attempts}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{run.total_prompt_tokens + run.total_output_tokens}</td>
                    <td className="py-1.5">
                      <button type="button" onClick={() => openRun(run.id)} className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700">
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

      {selected ? (
        <section className="mt-4 rounded-2xl border border-indigo-200 bg-white p-3.5">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-lg font-semibold text-gray-900">
              Run #{selected.id} — {selected.tenant_name ?? `tenant ${selected.tenant_id}`}
            </h2>
            <button type="button" onClick={() => setSelected(null)} className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700">
              Close
            </button>
          </div>

          {plan ? (
            <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Why this template</p>
              <p className="mt-1 text-sm text-gray-800">{plan.reasoning ?? '—'}</p>
              <p className="mt-1.5 text-xs text-gray-500">
                Template #{selected.final_template_id ?? '—'} · confidence {plan.confidence ?? '—'}
              </p>
              {plan.extra_instructions ? (
                <>
                  <p className="mt-2.5 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Instruction given to the drafter</p>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-gray-800">{plan.extra_instructions}</p>
                </>
              ) : null}
              {plan.extra_brain_sections?.length ? (
                <p className="mt-2.5 text-xs text-gray-600">
                  Extra brain sections: <span className="font-mono">{plan.extra_brain_sections.join(', ')}</span>
                </p>
              ) : null}
              {plan.alternatives?.length ? (
                <>
                  <p className="mt-2.5 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Rejected alternatives</p>
                  <ul className="mt-1 space-y-0.5 text-sm text-gray-700">
                    {plan.alternatives.map((alternative) => (
                      <li key={alternative.template_id}>
                        Template #{alternative.template_id} — {alternative.why_not}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          ) : null}

          {selected.checker_feedback ? (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Unresolved checker feedback</p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-amber-900">{selected.checker_feedback}</p>
            </div>
          ) : null}

          {selected.final_text ? (
            <div className="mt-3">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Final draft</p>
              <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800">{selected.final_text}</pre>
            </div>
          ) : null}

          <p className="mt-4 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Steps</p>
          <div className="mt-1.5 space-y-2">
            {selected.steps.map((step) => (
              <div key={step.id} className="rounded-xl border border-gray-200 p-2.5">
                <button
                  type="button"
                  onClick={() => setExpandedStepId(expandedStepId === step.id ? null : step.id)}
                  className="flex w-full items-center justify-between gap-3 text-left"
                >
                  <span className="text-sm font-semibold text-gray-900">
                    {step.step_index + 1}. {step.stage}
                    {step.error ? <span className="ml-2 text-xs text-rose-600">error</span> : null}
                  </span>
                  <span className="text-xs text-gray-500">
                    {step.model ?? '—'} · {(step.prompt_tokens ?? 0) + (step.output_tokens ?? 0)} tokens · {step.latency_ms ?? '—'}ms
                  </span>
                </button>
                {expandedStepId === step.id ? (
                  <div className="mt-2 space-y-2">
                    {step.error ? <p className="text-sm text-rose-600">{step.error}</p> : null}
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Prompt</p>
                      <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-gray-200 bg-gray-50 p-2.5 text-xs text-gray-800">{step.prompt ?? '—'}</pre>
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Response</p>
                      <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-gray-200 bg-gray-50 p-2.5 text-xs text-gray-800">{step.response ?? '—'}</pre>
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </main>
  )
}
