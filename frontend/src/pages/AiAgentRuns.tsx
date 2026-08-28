import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { getAiSettingsReturnHref } from '../lib/aiSettingsNavigation'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const PAGE_SIZE = 25
const eurFormatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 })

type AgentRun = {
  id: number
  tenant_id: number
  tenant_name: string | null
  channel: string
  mode: string
  display_mode: string
  status: string
  escalation_reason: string | null
  final_template_id: number | null
  final_template_name: string | null
  checker_feedback: string | null
  attempts: number
  total_prompt_tokens: number
  total_output_tokens: number
  total_cost: number | null
  pricing_missing: boolean
  duration_ms: number
  created_at: string
}

type AgentRunListResponse = {
  items: AgentRun[]
  total: number
}

type StatsPeriod = 'all' | 'today' | 'month'

type AgentRunStatsModel = {
  model: string
  prompt_tokens: number
  output_tokens: number
  total_tokens: number
  input_cost: number | null
  output_cost: number | null
  total_cost: number | null
  pricing_missing: boolean
}

type AgentRunStats = {
  period: StatsPeriod
  total_runs: number
  total_prompt_tokens: number
  total_output_tokens: number
  total_tokens: number
  total_cost: number | null
  any_pricing_missing: boolean
  by_model: AgentRunStatsModel[]
}

const STATS_PERIOD_TABS: Array<{ value: StatsPeriod; label: string; description: string }> = [
  { value: 'all', label: 'All time', description: 'Everything recorded so far' },
  { value: 'today', label: 'Today', description: 'UTC calendar day' },
  { value: 'month', label: 'This month', description: 'UTC month to date' },
]

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

function formatCost(value: number | null): string {
  if (value === null) return '—'
  return eurFormatter.format(value)
}

export default function AiAgentRuns() {
  useDocumentTitle('CRM - AI Runs')
  const token = useAuthStore((state) => state.token)
  const location = useLocation()
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [stats, setStats] = useState<AgentRunStats | null>(null)
  const [statsPeriod, setStatsPeriod] = useState<StatsPeriod>('all')
  const [statusFilter, setStatusFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [statsLoading, setStatsLoading] = useState(true)
  const [error, setError] = useState('')
  const [statsError, setStatsError] = useState('')

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  useEffect(() => {
    setOffset(0)
  }, [statusFilter])

  useEffect(() => {
    const controller = new AbortController()

    const load = async () => {
      try {
        setLoading(true)
        const params = new URLSearchParams()
        if (statusFilter) params.set('status', statusFilter)
        params.set('limit', String(PAGE_SIZE))
        params.set('offset', String(offset))
        const response = await fetch(`${API_BASE_URL}/api/ai-agent-runs?${params.toString()}`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error('Failed to load runs')
        }
        const data: AgentRunListResponse = await response.json()
        setRuns(data.items)
        setTotal(data.total)
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
  }, [authHeaders, offset, statusFilter])

  useEffect(() => {
    const controller = new AbortController()

    const loadStats = async () => {
      try {
        setStatsLoading(true)
        const params = new URLSearchParams()
        params.set('period', statsPeriod)
        const response = await fetch(`${API_BASE_URL}/api/ai-agent-runs/stats?${params.toString()}`, {
          headers: authHeaders,
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error('Failed to load AI usage stats')
        }
        const data: AgentRunStats = await response.json()
        setStats(data)
      } catch (err) {
        if (controller.signal.aborted) return
        setStatsError(err instanceof Error ? err.message : 'Failed to load AI usage stats')
      } finally {
        if (!controller.signal.aborted) setStatsLoading(false)
      }
    }

    setStatsError('')
    void loadStats()
    return () => controller.abort()
  }, [authHeaders, statsPeriod])

  const showingStart = total === 0 ? 0 : offset + 1
  const showingEnd = Math.min(offset + runs.length, total)
  const canGoBack = offset > 0
  const canGoForward = offset + PAGE_SIZE < total

  return (
    <main className="mx-auto max-w-6xl px-6 py-4">
      <Link to={getAiSettingsReturnHref(location.search, '/settings')} className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
      <h1 className="mt-1.5 text-2xl font-semibold text-gray-900">AI Planner Runs</h1>
      <p className="mt-1.5 text-sm text-gray-500">
        Every planner &rarr; drafter &rarr; checker execution, with the exact prompts and responses, the template that
        was chosen and why, and what it cost.
      </p>

      <section className="mt-4 rounded-3xl border border-cyan-100 bg-gradient-to-br from-cyan-50 via-white to-sky-50 p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Token and cost overview</h2>
          </div>
          {stats?.any_pricing_missing ? (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">Partial cost: some models are missing pricing</span>
          ) : null}
        </div>

        <div className="mt-4 inline-flex rounded-2xl border border-cyan-100 bg-white/80 p-1 shadow-sm">
          {STATS_PERIOD_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setStatsPeriod(tab.value)}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
                statsPeriod === tab.value ? 'bg-cyan-600 text-white shadow-sm' : 'text-gray-600 hover:bg-cyan-50'
              }`}
            >
              <span className="block">{tab.label}</span>
              <span className={`block text-[11px] font-normal ${statsPeriod === tab.value ? 'text-cyan-100' : 'text-gray-400'}`}>
                {tab.description}
              </span>
            </button>
          ))}
        </div>

        {statsError ? <p className="mt-3 text-sm text-rose-600">{statsError}</p> : null}

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-2xl border border-white/70 bg-white/90 p-4 shadow-sm backdrop-blur">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Runs</p>
            <p className="mt-2 text-3xl font-semibold text-gray-900">{statsLoading ? '…' : stats?.total_runs ?? 0}</p>
          </div>
          <div className="rounded-2xl border border-white/70 bg-white/90 p-4 shadow-sm backdrop-blur">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Tokens</p>
            <p className="mt-2 text-3xl font-semibold text-gray-900">{statsLoading ? '…' : stats?.total_tokens ?? 0}</p>
            <p className="mt-1 text-xs text-gray-500">
              {statsLoading ? 'Loading usage totals' : `${stats?.total_prompt_tokens ?? 0} prompt · ${stats?.total_output_tokens ?? 0} output`}
            </p>
          </div>
          <div className="rounded-2xl border border-white/70 bg-white/90 p-4 shadow-sm backdrop-blur">
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Estimated cost</p>
            <p className="mt-2 text-3xl font-semibold text-gray-900">
              {statsLoading ? '…' : formatCost(stats?.total_cost ?? null)}
            </p>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto rounded-2xl border border-cyan-100 bg-white/80">
          {statsLoading ? (
            <p className="p-4 text-sm text-gray-500">Loading AI usage stats...</p>
          ) : (stats?.by_model.length ?? 0) === 0 ? (
            <p className="p-4 text-sm text-gray-500">No AI steps with token usage have been recorded yet.</p>
          ) : (
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs uppercase tracking-[0.12em] text-gray-500">
                  <th className="px-4 py-3">Model</th>
                  <th className="px-4 py-3">Prompt</th>
                  <th className="px-4 py-3">Output</th>
                  <th className="px-4 py-3">Total tokens</th>
                  <th className="px-4 py-3">Cost</th>
                  <th className="px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {stats?.by_model.map((row) => (
                  <tr key={row.model} className="border-t border-gray-100">
                    <td className="px-4 py-3 font-medium text-gray-900">{row.model}</td>
                    <td className="px-4 py-3 text-gray-600">{row.prompt_tokens.toLocaleString()}</td>
                    <td className="px-4 py-3 text-gray-600">{row.output_tokens.toLocaleString()}</td>
                    <td className="px-4 py-3 text-gray-600">{row.total_tokens.toLocaleString()}</td>
                    <td className="px-4 py-3 text-gray-600">
                      {row.pricing_missing ? '—' : formatCost(row.total_cost)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${row.pricing_missing ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>
                        {row.pricing_missing ? 'Missing pricing' : 'Priced'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {error ? <p className="mt-3 text-sm text-rose-600">{error}</p> : null}

      <section className="mt-3 rounded-2xl border border-gray-200 bg-white p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 pb-3">
          <p className="text-sm text-gray-500">
            {total ? `Showing ${showingStart}-${showingEnd} of ${total}` : '0 runs'}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
              disabled={!canGoBack || loading}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Prev
            </button>
            <button
              type="button"
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
              disabled={!canGoForward || loading}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
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
        {loading ? (
          <p className="py-3 text-sm text-gray-500">Loading...</p>
        ) : runs.length === 0 ? (
          <p className="py-3 text-sm text-gray-500">No runs recorded yet.</p>
        ) : (
          <div className="overflow-x-auto pt-3">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-[0.12em] text-gray-500">
                  <th className="py-1.5 pr-3">Run #</th>
                  <th className="py-1.5 pr-3">When</th>
                  <th className="py-1.5 pr-3">Tenant</th>
                  <th className="py-1.5 pr-3">Channel</th>
                  <th className="py-1.5 pr-3">Mode</th>
                  <th className="py-1.5 pr-3">Status</th>
                  <th className="py-1.5 pr-3">Template</th>
                  <th className="py-1.5 pr-3">Tries</th>
                  <th className="py-1.5 pr-3">Tokens</th>
                  <th className="py-1.5 pr-3">Cost</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-t border-gray-100">
                    <td className="py-1.5 pr-3 text-gray-600">{run.id}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{new Date(run.created_at).toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-gray-900">{run.tenant_name ?? `#${run.tenant_id}`}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{run.channel}</td>
                    <td className="py-1.5 pr-3 text-gray-600">{run.display_mode}</td>
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
                    <td className="py-1.5 pr-3 text-gray-600">
                      {run.pricing_missing ? '—' : formatCost(run.total_cost)}
                    </td>
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
