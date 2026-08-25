import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
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

type AgentRunDetail = AgentRun & {
  final_text: string | null
  steps: AgentRunStep[]
  template_names: Record<number, string>
}

function templateLabel(id: number | null, name?: string | null): string {
  if (name) return name
  if (id != null) return `Template #${id} (deleted)`
  return '—'
}

export default function AiAgentRunDetail() {
  const token = useAuthStore((state) => state.token)
  const { runId } = useParams()
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading')
  const [error, setError] = useState('')
  const [run, setRun] = useState<AgentRunDetail | null>(null)
  const [expandedStepId, setExpandedStepId] = useState<number | null>(null)

  useDocumentTitle(run ? `CRM - Run #${run.id} - ${run.tenant_name ?? 'Unknown Tenant'}` : `CRM - Run #${runId}`)

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  useEffect(() => {
    if (!runId) {
      setError('Run not found.')
      setStatus('error')
      return
    }

    const controller = new AbortController()
    setStatus('loading')
    setError('')
    setRun(null)
    setExpandedStepId(null)

    const load = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/ai-agent-runs/${runId}`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!response.ok) {
          if (response.status === 404) {
            throw new Error('Run not found.')
          }
          const data = await response.json().catch(() => null)
          throw new Error(data?.detail || 'Failed to load the run')
        }
        const data: AgentRunDetail = await response.json()
        setRun(data)
        setStatus('ready')
      } catch (err) {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Failed to load the run')
        setStatus('error')
      }
    }

    void load()
    return () => controller.abort()
  }, [authHeaders, runId])

  const plannerStep = run?.steps.find((step) => step.stage === 'planner')
  const plan = (plannerStep?.parsed ?? null) as
    | {
        reasoning?: string
        confidence?: number
        extra_instructions?: string
        extra_brain_sections?: string[]
        alternatives?: { template_id: number; why_not: string }[]
      }
    | null

  return (
    <main className="mx-auto max-w-4xl px-4 py-4">
      <h1 className="text-lg font-semibold text-gray-900">AI Planner Run Detail</h1>
      <p className="mt-1 text-sm text-gray-500">
        Run information fetched directly from the URL, with the planning rationale, checker feedback, final draft,
        and every step in sequence.
      </p>

      {status === 'loading' ? <p className="mt-4 text-sm text-gray-500">Loading...</p> : null}
      {status === 'error' ? <p className="mt-4 text-sm text-rose-600">{error}</p> : null}

      {status === 'ready' && run ? (
        <div className="mt-3 space-y-3">
          <h2 className="text-lg font-semibold text-gray-900">
            Run #{run.id} — {run.tenant_name ?? `tenant ${run.tenant_id}`}
          </h2>

          {plan ? (
            <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Why this template</p>
              <p className="mt-1 text-sm text-gray-800">{plan.reasoning ?? '—'}</p>
              <p className="mt-1.5 text-xs text-gray-500">
                {templateLabel(run.final_template_id, run.final_template_name)} · confidence {plan.confidence ?? '—'}
              </p>
              {plan.extra_instructions ? (
                <>
                  <p className="mt-2.5 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">
                    Instruction given to the drafter
                  </p>
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
                  <p className="mt-2.5 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">
                    Rejected alternatives
                  </p>
                  <ul className="mt-1 space-y-0.5 text-sm text-gray-700">
                    {plan.alternatives.map((alternative) => (
                      <li key={alternative.template_id}>
                        {templateLabel(alternative.template_id, run.template_names[alternative.template_id])} — {alternative.why_not}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </div>
          ) : null}

          {run.checker_feedback ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Unresolved checker feedback</p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-amber-900">{run.checker_feedback}</p>
            </div>
          ) : null}

          {run.final_text ? (
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Final draft</p>
              <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-800">
                {run.final_text}
              </pre>
            </div>
          ) : null}

          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Steps</p>
            <div className="mt-1.5 space-y-2">
              {run.steps.map((step) => (
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
                        <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-gray-200 bg-gray-50 p-2.5 text-xs text-gray-800">
                          {step.prompt ?? '—'}
                        </pre>
                      </div>
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Response</p>
                        <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-gray-200 bg-gray-50 p-2.5 text-xs text-gray-800">
                          {step.response ?? '—'}
                        </pre>
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}
