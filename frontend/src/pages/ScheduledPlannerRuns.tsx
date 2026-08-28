import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import InlineSpinner from '../components/InlineSpinner'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const PREVIEW_DEBOUNCE_MS = 300

type LastMessageDirection = 'inbound' | 'outbound' | 'either' | ''

type ScheduleForm = {
  id: number | null
  name: string
  extra_instructions: string
  enabled: boolean
  run_time_local: string
  status_filter: string[]
  last_message_within_days: string
  last_message_direction: LastMessageDirection
}

type BulkPlannerSchedule = {
  id: number
  name: string
  extra_instructions: string | null
  enabled: boolean
  run_time_local: string
  status_filter: string[]
  last_message_within_days: number | null
  last_message_direction: 'inbound' | 'outbound' | 'either' | null
  last_run_at: string | null
  next_run_at: string
  created_by_user_id: number | null
  created_at: string
  updated_at: string
  last_matched_tenant_count: number | null
  last_run_status: 'running' | 'completed' | 'failed' | null
  last_trigger_reason: 'scheduled' | 'catch_up' | null
}

type BulkPlannerRun = {
  id: number
  schedule_id: number
  started_at: string
  completed_at: string | null
  trigger_reason: 'scheduled' | 'catch_up'
  matched_tenant_count: number
  status: 'running' | 'completed' | 'failed'
}

type BulkPlannerRunList = {
  total: number
  items: BulkPlannerRun[]
}

type BulkPlannerRunResult = {
  id: number
  run_id: number
  tenant_id: number
  tenant_name: string | null
  channel: string
  outcome: 'success' | 'skipped' | 'error'
  skip_reason: string | null
  error_message: string | null
  draft_id: number | null
  created_at: string
}

type PreviewTenant = {
  id: number
  name: string
  booking_id: string
  booking_status: string | null
}

type PreviewResponse = {
  matched_tenant_count: number
  tenants: PreviewTenant[]
}

const emptyForm = (): ScheduleForm => ({
  id: null,
  name: '',
  extra_instructions: '',
  enabled: true,
  run_time_local: '09:00',
  status_filter: [],
  last_message_within_days: '',
  last_message_direction: '',
})

function toForm(schedule: BulkPlannerSchedule): ScheduleForm {
  return {
    id: schedule.id,
    name: schedule.name,
    extra_instructions: schedule.extra_instructions ?? '',
    enabled: schedule.enabled,
    run_time_local: schedule.run_time_local.slice(0, 5),
    status_filter: schedule.status_filter || [],
    last_message_within_days: schedule.last_message_within_days === null ? '' : String(schedule.last_message_within_days),
    last_message_direction: schedule.last_message_direction ?? '',
  }
}

function previewPayload(form: ScheduleForm) {
  return {
    status_filter: form.status_filter,
    last_message_within_days: form.last_message_within_days.trim() ? Number(form.last_message_within_days) : null,
    last_message_direction: form.last_message_direction || null,
  }
}

function savePayload(form: ScheduleForm) {
  return {
    name: form.name.trim(),
    extra_instructions: form.extra_instructions.trim() || null,
    enabled: form.enabled,
    run_time_local: `${form.run_time_local}:00`,
    ...previewPayload(form),
  }
}

function formatDateTime(value: string | null) {
  if (!value) return 'Never'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Europe/Amsterdam',
  }).format(new Date(value))
}

function badgeClasses(kind: 'success' | 'skipped' | 'error' | 'running' | 'completed' | 'failed') {
  if (kind === 'success' || kind === 'completed') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (kind === 'skipped') return 'bg-amber-50 text-amber-700 border-amber-200'
  if (kind === 'running') return 'bg-sky-50 text-sky-700 border-sky-200'
  return 'bg-rose-50 text-rose-700 border-rose-200'
}

export default function ScheduledPlannerRuns() {
  useDocumentTitle('CRM - Planner Schedules')
  const token = useAuthStore((state) => state.token)
  const [schedules, setSchedules] = useState<BulkPlannerSchedule[]>([])
  const [statuses, setStatuses] = useState<string[]>([])
  const [form, setForm] = useState<ScheduleForm>(emptyForm)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [preview, setPreview] = useState<PreviewResponse>({ matched_tenant_count: 0, tenants: [] })
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [expandedScheduleIds, setExpandedScheduleIds] = useState<Set<number>>(new Set())
  const [runsByScheduleId, setRunsByScheduleId] = useState<Record<number, BulkPlannerRunList>>({})
  const [loadingRuns, setLoadingRuns] = useState<Record<number, boolean>>({})
  const [expandedRunIds, setExpandedRunIds] = useState<Set<number>>(new Set())
  const [resultsByRunId, setResultsByRunId] = useState<Record<number, BulkPlannerRunResult[]>>({})
  const [loadingResults, setLoadingResults] = useState<Record<number, boolean>>({})

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  const loadSchedules = useCallback(async () => {
    if (!token) return
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/bulk-planner-schedules`, { headers: authHeaders })
      if (!response.ok) return
      const data = await response.json()
      setSchedules(Array.isArray(data) ? data : [])
    } finally {
      setLoading(false)
    }
  }, [authHeaders, token])

  useEffect(() => {
    if (!token) return
    const loadStaticData = async () => {
      const [scheduleResponse, statusResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/api/bulk-planner-schedules`, { headers: authHeaders }),
        fetch(`${API_BASE_URL}/api/tenants/statuses`, { headers: authHeaders }),
      ])
      if (scheduleResponse.ok) {
        const scheduleData = await scheduleResponse.json()
        setSchedules(Array.isArray(scheduleData) ? scheduleData : [])
      }
      if (statusResponse.ok) {
        const statusData = await statusResponse.json()
        setStatuses(Array.isArray(statusData) ? statusData : [])
      }
    }
    loadStaticData().catch(() => undefined)
  }, [token])

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    setPreviewLoading(true)
    setPreviewError('')
    const timeoutId = window.setTimeout(async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/bulk-planner-schedules/preview`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
          body: JSON.stringify(previewPayload(form)),
          signal: controller.signal,
        })
        const data = await response.json().catch(() => null)
        if (!response.ok) {
          setPreviewError(data?.detail ?? 'Preview failed')
          setPreview({ matched_tenant_count: 0, tenants: [] })
          return
        }
        setPreview(data as PreviewResponse)
      } catch (error) {
        if ((error as Error).name === 'AbortError') return
        setPreviewError('Preview failed')
      } finally {
        setPreviewLoading(false)
      }
    }, PREVIEW_DEBOUNCE_MS)
    return () => {
      controller.abort()
      window.clearTimeout(timeoutId)
    }
  }, [token, form])

  const loadScheduleDetail = async (scheduleId: number) => {
    const response = await fetch(`${API_BASE_URL}/api/bulk-planner-schedules/${scheduleId}`, { headers: authHeaders })
    if (!response.ok) return
    const data = (await response.json()) as BulkPlannerSchedule
    setForm(toForm(data))
    setMessage('')
  }

  const loadRuns = useCallback(async (scheduleId: number) => {
    setLoadingRuns((current) => ({ ...current, [scheduleId]: true }))
    try {
      const response = await fetch(`${API_BASE_URL}/api/bulk-planner-schedules/${scheduleId}/runs`, { headers: authHeaders })
      if (!response.ok) return
      const data = (await response.json()) as BulkPlannerRunList
      setRunsByScheduleId((current) => ({ ...current, [scheduleId]: data }))
    } finally {
      setLoadingRuns((current) => ({ ...current, [scheduleId]: false }))
    }
  }, [authHeaders])

  const loadResults = useCallback(async (scheduleId: number, runId: number) => {
    setLoadingResults((current) => ({ ...current, [runId]: true }))
    try {
      const response = await fetch(`${API_BASE_URL}/api/bulk-planner-schedules/${scheduleId}/runs/${runId}/results`, { headers: authHeaders })
      if (!response.ok) return
      const data = await response.json()
      setResultsByRunId((current) => ({ ...current, [runId]: Array.isArray(data) ? data : [] }))
    } finally {
      setLoadingResults((current) => ({ ...current, [runId]: false }))
    }
  }, [authHeaders])

  const hasRunningVisible = useMemo(
    () =>
      schedules.some((schedule) => schedule.last_run_status === 'running') ||
      Object.values(runsByScheduleId).some((runList) => runList.items.some((run) => run.status === 'running')),
    [runsByScheduleId, schedules],
  )

  // Polling reads the latest runsByScheduleId through a ref rather than as a dependency: the
  // poll itself refreshes that state every tick, so depending on it directly would tear down
  // and rebuild the interval (plus fire an extra immediate poll) on every single tick, turning
  // a 7s poll into a back-to-back fetch loop for as long as something stays "running".
  const runsByScheduleIdRef = useRef(runsByScheduleId)
  useEffect(() => {
    runsByScheduleIdRef.current = runsByScheduleId
  }, [runsByScheduleId])

  useEffect(() => {
    if (!token || !hasRunningVisible) return
    let cancelled = false

    const pollRunningState = async () => {
      try {
        await loadSchedules()
        await Promise.all(Array.from(expandedScheduleIds).map((scheduleId) => loadRuns(scheduleId)))
        const expandedRunTargets = Object.entries(runsByScheduleIdRef.current).flatMap(([scheduleId, runList]) =>
          runList.items
            .filter((run) => expandedRunIds.has(run.id))
            .map((run) => ({ scheduleId: Number(scheduleId), runId: run.id })),
        )
        await Promise.all(expandedRunTargets.map(({ scheduleId, runId }) => loadResults(scheduleId, runId)))
      } catch {
        // Ignore transient polling errors; the next tick will retry.
      }
      if (cancelled) return
    }

    void pollRunningState()
    const intervalId = window.setInterval(() => {
      void pollRunningState()
    }, 7000)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [expandedRunIds, expandedScheduleIds, hasRunningVisible, loadResults, loadRuns, loadSchedules, token])

  const toggleScheduleExpanded = async (scheduleId: number) => {
    const isExpanded = expandedScheduleIds.has(scheduleId)
    setExpandedScheduleIds((current) => {
      const next = new Set(current)
      if (isExpanded) next.delete(scheduleId)
      else next.add(scheduleId)
      return next
    })
    if (!isExpanded && !runsByScheduleId[scheduleId]) {
      await loadRuns(scheduleId)
    }
  }

  const toggleRunExpanded = async (scheduleId: number, runId: number) => {
    const isExpanded = expandedRunIds.has(runId)
    setExpandedRunIds((current) => {
      const next = new Set(current)
      if (isExpanded) next.delete(runId)
      else next.add(runId)
      return next
    })
    if (!isExpanded && !resultsByRunId[runId]) {
      await loadResults(scheduleId, runId)
    }
  }

  const handleSave = async () => {
    if (!form.name.trim() || !form.run_time_local || saving) return
    setSaving(true)
    setMessage('')
    try {
      const isEditing = form.id !== null
      const response = await fetch(
        `${API_BASE_URL}/api/bulk-planner-schedules${isEditing ? `/${form.id}` : ''}`,
        {
          method: isEditing ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
          body: JSON.stringify(savePayload(form)),
        },
      )
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setMessage(data?.detail ?? 'Failed to save schedule')
        return
      }
      setMessage(isEditing ? 'Schedule updated.' : 'Schedule created.')
      setForm(toForm(data as BulkPlannerSchedule))
      await loadSchedules()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (form.id === null) return
    const response = await fetch(`${API_BASE_URL}/api/bulk-planner-schedules/${form.id}`, {
      method: 'DELETE',
      headers: authHeaders,
    })
    if (!response.ok) {
      setMessage('Failed to delete schedule')
      return
    }
    setForm(emptyForm())
    setMessage('Schedule deleted.')
    await loadSchedules()
  }

  const toggleScheduleEnabled = async (schedule: BulkPlannerSchedule, enabled: boolean) => {
    const response = await fetch(`${API_BASE_URL}/api/bulk-planner-schedules/${schedule.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
      body: JSON.stringify({ enabled }),
    })
    if (!response.ok) return
    const updated = (await response.json()) as BulkPlannerSchedule
    setSchedules((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    if (form.id === updated.id) setForm(toForm(updated))
  }

  return (
    <main className="mx-auto max-w-7xl px-6 py-4">
      <Link to="/settings" className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
      <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="mt-1.5 text-2xl font-semibold text-gray-900">Planner schedules</h1>
              <p className="mt-1 text-sm text-gray-500">
                Run the existing tenant planner in bulk every day at a fixed Europe/Amsterdam time.
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setForm(emptyForm())
                setMessage('')
              }}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
            >
              New schedule
            </button>
          </div>

          <div className="mt-4 space-y-3">
            {loading && !schedules.length ? <p className="text-sm text-gray-500">Loading schedules...</p> : null}
            {!loading && !schedules.length ? <p className="text-sm text-gray-500">No schedules yet.</p> : null}
            {schedules.map((schedule) => {
              const expanded = expandedScheduleIds.has(schedule.id)
              const runList = runsByScheduleId[schedule.id]
              return (
                <div key={schedule.id} className="rounded-2xl border border-gray-200 bg-gray-50/70 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-base font-semibold text-gray-900">{schedule.name}</h2>
                        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] ${schedule.enabled ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-gray-300 bg-white text-gray-500'}`}>
                          {schedule.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        {schedule.last_run_status ? (
                          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] ${badgeClasses(schedule.last_run_status)}`}>
                            {schedule.last_run_status === 'running' ? <InlineSpinner className="h-3 w-3" /> : null}
                            {schedule.last_run_status}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-sm text-gray-600">
                        Daily at {schedule.run_time_local.slice(0, 5)} Amsterdam time. Next run {formatDateTime(schedule.next_run_at)}.
                      </p>
                      <p className="mt-1 text-xs text-gray-500">
                        Last run {formatDateTime(schedule.last_run_at)}. Last matched {schedule.last_matched_tenant_count ?? 'n/a'} tenant(s).
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <label className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700">
                        <input
                          type="checkbox"
                          checked={schedule.enabled}
                          onChange={(event) => toggleScheduleEnabled(schedule, event.target.checked)}
                          className="h-4 w-4 rounded border-gray-300"
                        />
                        Enabled
                      </label>
                      <button
                        type="button"
                        onClick={() => loadScheduleDetail(schedule.id)}
                        className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleScheduleExpanded(schedule.id)}
                        className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-gray-800"
                      >
                        {expanded ? 'Hide history' : 'Show history'}
                      </button>
                    </div>
                  </div>

                  {expanded ? (
                    <div className="mt-3 rounded-2xl border border-gray-200 bg-white p-3">
                      {loadingRuns[schedule.id] && !runList ? <p className="text-sm text-gray-500">Loading run history...</p> : null}
                      {!loadingRuns[schedule.id] && (!runList || !runList.items.length) ? <p className="text-sm text-gray-500">No runs yet.</p> : null}
                      <div className="space-y-2">
                        {runList?.items.map((run) => {
                          const runExpanded = expandedRunIds.has(run.id)
                          const results = resultsByRunId[run.id]
                          return (
                            <div key={run.id} className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="text-sm font-semibold text-gray-900">Run #{run.id}</span>
                                  <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] ${badgeClasses(run.status)}`}>
                                    {run.status === 'running' ? <InlineSpinner className="h-3 w-3" /> : null}
                                    {run.status}
                                  </span>
                                  <span className="rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] text-gray-600">
                                    {run.trigger_reason === 'catch_up' ? 'Catch-up' : 'Scheduled'}
                                  </span>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => toggleRunExpanded(schedule.id, run.id)}
                                  className="rounded-lg border border-gray-300 bg-white px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50"
                                >
                                  {runExpanded ? 'Hide results' : 'Show results'}
                                </button>
                              </div>
                              <p className="mt-1 text-xs text-gray-500">
                                Started {formatDateTime(run.started_at)}. Completed {formatDateTime(run.completed_at)}. Matched {run.matched_tenant_count} tenant(s).
                              </p>
                              {runExpanded ? (
                                <div className="mt-2 space-y-2">
                                  {loadingResults[run.id] && !results ? <p className="text-sm text-gray-500">Loading results...</p> : null}
                                  {!loadingResults[run.id] && results && !results.length ? <p className="text-sm text-gray-500">No per-tenant results.</p> : null}
                                  {results?.map((result) => (
                                    <div key={result.id} className="rounded-xl border border-gray-200 bg-white p-2.5">
                                      <div className="flex flex-wrap items-center gap-2">
                                        <span className="text-sm font-semibold text-gray-900">{result.tenant_name ?? `Tenant #${result.tenant_id}`}</span>
                                        <span className="text-xs uppercase tracking-[0.2em] text-gray-500">{result.channel}</span>
                                        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.2em] ${badgeClasses(result.outcome)}`}>
                                          {result.outcome}
                                        </span>
                                        {result.draft_id ? <span className="text-xs text-gray-500">Draft #{result.draft_id}</span> : null}
                                      </div>
                                      {result.skip_reason ? <p className="mt-1 text-xs text-amber-700">{result.skip_reason}</p> : null}
                                      {result.error_message ? <p className="mt-1 text-xs text-rose-700">{result.error_message}</p> : null}
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </section>

        <section className="space-y-4">
          <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
            <h2 className="text-lg font-semibold text-gray-900">{form.id === null ? 'Create schedule' : `Edit schedule #${form.id}`}</h2>
            <p className="mt-1 text-sm text-gray-500">
              Filters are re-evaluated fresh at each run and combined with AND.
            </p>

            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-schedule-name">
                  Name
                </label>
                <input
                  id="planner-schedule-name"
                  type="text"
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="Confirmed recent inbound replies"
                  className="mt-1.5 w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-schedule-extra-instructions">
                  Extra instructions
                </label>
                <textarea
                  id="planner-schedule-extra-instructions"
                  value={form.extra_instructions}
                  onChange={(event) => setForm((current) => ({ ...current, extra_instructions: event.target.value }))}
                  placeholder="Add extra guidance that should be threaded into the planner prompt."
                  rows={4}
                  className="mt-1.5 w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                />
                <p className="mt-1 text-xs text-gray-500">This is passed to the planner like an operator note.</p>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-schedule-time">
                    Daily time
                  </label>
                  <input
                    id="planner-schedule-time"
                    type="time"
                    value={form.run_time_local}
                    onChange={(event) => setForm((current) => ({ ...current, run_time_local: event.target.value }))}
                    className="mt-1.5 w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  />
                  <p className="mt-1 text-xs text-gray-500">Europe/Amsterdam wall-clock time.</p>
                </div>

                <label className="mt-6 inline-flex items-center gap-2 rounded-xl border border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-700 sm:mt-0 sm:self-end">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(event) => setForm((current) => ({ ...current, enabled: event.target.checked }))}
                    className="h-4 w-4 rounded border-gray-300"
                  />
                  Enabled
                </label>
              </div>

              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Booking status</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {statuses.map((status) => {
                    const checked = form.status_filter.includes(status)
                    return (
                      <label key={status} className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm ${checked ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-gray-300 bg-white text-gray-700'}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setForm((current) => ({
                              ...current,
                              status_filter: checked
                                ? current.status_filter.filter((value) => value !== status)
                                : [...current.status_filter, status],
                            }))
                          }
                          className="h-4 w-4 rounded border-gray-300"
                        />
                        {status}
                      </label>
                    )
                  })}
                  {!statuses.length ? <span className="text-sm text-gray-500">No statuses loaded yet.</span> : null}
                </div>
                <p className="mt-1 text-xs text-gray-500">Leave empty to match any tenant status.</p>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-schedule-last-days">
                    Last message within days
                  </label>
                  <input
                    id="planner-schedule-last-days"
                    type="number"
                    min={0}
                    value={form.last_message_within_days}
                    onChange={(event) => setForm((current) => ({ ...current, last_message_within_days: event.target.value }))}
                    placeholder="7"
                    className="mt-1.5 w-full rounded-xl border border-gray-300 px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500" htmlFor="planner-schedule-direction">
                    Direction
                  </label>
                  <select
                    id="planner-schedule-direction"
                    value={form.last_message_direction}
                    onChange={(event) => setForm((current) => ({ ...current, last_message_direction: event.target.value as LastMessageDirection }))}
                    className="mt-1.5 w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500"
                  >
                    <option value="">No filter</option>
                    <option value="either">Either inbound or outbound</option>
                    <option value="inbound">Inbound only</option>
                    <option value="outbound">Outbound only</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleSave}
                disabled={saving || !form.name.trim() || !form.run_time_local}
                className="rounded-xl bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? 'Saving...' : form.id === null ? 'Create schedule' : 'Save changes'}
              </button>
              {form.id !== null ? (
                <button
                  type="button"
                  onClick={handleDelete}
                  className="rounded-xl border border-rose-300 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-100"
                >
                  Delete
                </button>
              ) : null}
            </div>
            {message ? <p className="mt-3 text-sm text-gray-600">{message}</p> : null}
          </div>

          <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Live preview</h2>
                <p className="mt-1 text-sm text-gray-500">Updates as you change the filter fields.</p>
              </div>
              {previewLoading ? <span className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-700">Refreshing...</span> : null}
            </div>
            <p className="mt-3 text-3xl font-semibold text-gray-900">{preview.matched_tenant_count}</p>
            <p className="text-sm text-gray-500">matching tenant(s)</p>
            {previewError ? <p className="mt-2 text-sm text-rose-600">{previewError}</p> : null}
            <div className="mt-4 space-y-2">
              {preview.tenants.map((tenant) => (
                <div key={tenant.id} className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2">
                  <p className="text-sm font-semibold text-gray-900">{tenant.name}</p>
                  <p className="text-xs text-gray-500">
                    {tenant.booking_id}
                    {tenant.booking_status ? ` • ${tenant.booking_status}` : ''}
                  </p>
                </div>
              ))}
              {!preview.tenants.length ? <p className="text-sm text-gray-500">No preview tenants for the current filters.</p> : null}
            </div>
          </div>
        </section>
      </div>
    </main>
  )
}
