import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { type AgentRole, type AiAgentProfile, type PromptBlockDefinition } from '../types/aiAgentProfile'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type ProfileForm = Omit<AiAgentProfile, 'id' | 'escalate_keywords' | 'instructions' | 'model'> & {
  id: number | null
  escalate_keywords: string
  instructions: string
  model: string
}

type FieldRelevance = {
  model: boolean
  temperature: boolean
  max_output_tokens: boolean
  history_limit: boolean
  history_channels: boolean
  history_lookback_days: boolean
  include_beds24: boolean
  include_payments: boolean
  include_notes: boolean
  include_availability: boolean
  include_tenant_brain: boolean
  include_brain_index: boolean
  match_inbound_language: boolean
  escalate_keywords: boolean
  min_confidence: boolean
  on_no_template_match: boolean
  max_redraft_attempts: boolean
  block_auto_send_on_fail: boolean
  daily_token_cap: boolean
  prompt_blocks: boolean
}

const LABEL = 'block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500'
const INPUT =
  'mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500'

const INSTRUCTIONS_PLACEHOLDER: Record<AgentRole, string> = {
  planner:
    'e.g. Always prefer the most specific template. If the guest asks several things, pick the template covering the most urgent one and mention the rest in the instruction.',
  checker:
    'e.g. Reject the draft if it invents a price, promises anything not in the knowledge base, or is longer than four sentences.',
  drafter: "e.g. Stay warm and concise, mirror the guest's tone, and end with a friendly sign-off.",
  brain_writer: 'e.g. Capture facts, policies, or patterns worth remembering long-term, not one-off replies.',
  action_writer: 'e.g. Describe the exact condition that should create a task, and keep the trigger unambiguous.',
  memory_redo: 'e.g. Suggest a rule only after the same correction shows up more than once.',
  memory_qa: 'e.g. Answer only from the provided context; if the answer is missing, say so clearly.',
}

const FIELD_RELEVANCE: Record<AgentRole, FieldRelevance> = {
  planner: {
    model: true,
    temperature: true,
    max_output_tokens: true,
    history_limit: true,
    history_channels: true,
    history_lookback_days: true,
    include_beds24: true,
    include_payments: true,
    include_notes: true,
    include_availability: true,
    include_tenant_brain: true,
    include_brain_index: true,
    match_inbound_language: true,
    escalate_keywords: true,
    min_confidence: true,
    on_no_template_match: true,
    max_redraft_attempts: false,
    block_auto_send_on_fail: false,
    daily_token_cap: true,
    prompt_blocks: true,
  },
  checker: {
    model: true,
    temperature: true,
    max_output_tokens: true,
    history_limit: true,
    history_channels: true,
    history_lookback_days: true,
    include_beds24: true,
    include_payments: true,
    include_notes: true,
    include_availability: true,
    include_tenant_brain: true,
    include_brain_index: true,
    match_inbound_language: true,
    escalate_keywords: false,
    min_confidence: false,
    on_no_template_match: false,
    max_redraft_attempts: true,
    block_auto_send_on_fail: true,
    daily_token_cap: true,
    prompt_blocks: true,
  },
  drafter: {
    model: false,
    temperature: false,
    max_output_tokens: false,
    history_limit: false,
    history_channels: false,
    history_lookback_days: false,
    include_beds24: false,
    include_payments: false,
    include_notes: false,
    include_availability: false,
    include_tenant_brain: false,
    include_brain_index: false,
    match_inbound_language: false,
    escalate_keywords: false,
    min_confidence: false,
    on_no_template_match: false,
    max_redraft_attempts: false,
    block_auto_send_on_fail: false,
    daily_token_cap: false,
    prompt_blocks: true,
  },
  brain_writer: {
    model: true,
    temperature: true,
    max_output_tokens: true,
    history_limit: true,
    history_channels: true,
    history_lookback_days: true,
    include_beds24: true,
    include_payments: true,
    include_notes: true,
    include_availability: false,
    include_tenant_brain: false,
    include_brain_index: false,
    match_inbound_language: false,
    escalate_keywords: false,
    min_confidence: false,
    on_no_template_match: false,
    max_redraft_attempts: false,
    block_auto_send_on_fail: false,
    daily_token_cap: false,
    prompt_blocks: true,
  },
  action_writer: {
    model: true,
    temperature: true,
    max_output_tokens: true,
    history_limit: true,
    history_channels: false,
    history_lookback_days: true,
    include_beds24: true,
    include_payments: false,
    include_notes: true,
    include_availability: false,
    include_tenant_brain: false,
    include_brain_index: false,
    match_inbound_language: false,
    escalate_keywords: false,
    min_confidence: false,
    on_no_template_match: false,
    max_redraft_attempts: false,
    block_auto_send_on_fail: false,
    daily_token_cap: false,
    prompt_blocks: true,
  },
  memory_redo: {
    model: true,
    temperature: true,
    max_output_tokens: true,
    history_limit: false,
    history_channels: false,
    history_lookback_days: false,
    include_beds24: false,
    include_payments: false,
    include_notes: false,
    include_availability: false,
    include_tenant_brain: false,
    include_brain_index: false,
    match_inbound_language: false,
    escalate_keywords: false,
    min_confidence: false,
    on_no_template_match: false,
    max_redraft_attempts: false,
    block_auto_send_on_fail: false,
    daily_token_cap: false,
    prompt_blocks: true,
  },
  memory_qa: {
    model: true,
    temperature: true,
    max_output_tokens: true,
    history_limit: true,
    history_channels: true,
    history_lookback_days: true,
    include_beds24: true,
    include_payments: true,
    include_notes: true,
    include_availability: true,
    include_tenant_brain: false,
    include_brain_index: true,
    match_inbound_language: false,
    escalate_keywords: false,
    min_confidence: false,
    on_no_template_match: false,
    max_redraft_attempts: false,
    block_auto_send_on_fail: false,
    daily_token_cap: false,
    prompt_blocks: true,
  },
}

function emptyForm(role: AgentRole): ProfileForm {
  return {
    id: null,
    name: '',
    role,
    is_default: false,
    is_active: true,
    instructions: '',
    model: '',
    temperature: role === 'checker' ? 0 : 0.2,
    max_output_tokens: 2048,
    history_limit: 40,
    history_channels: 'both',
    history_lookback_days: null,
    include_beds24: true,
    include_payments: false,
    include_notes: true,
    include_availability: false,
    include_tenant_brain: false,
    include_brain_index: true,
    match_inbound_language: true,
    escalate_keywords: '',
    on_no_template_match: 'escalate',
    min_confidence: 0.5,
    max_redraft_attempts: 2,
    block_auto_send_on_fail: true,
    daily_token_cap: null,
    prompt_blocks: {},
  }
}

function toFormState(profile: AiAgentProfile): ProfileForm {
  return {
    ...profile,
    id: profile.id,
    instructions: profile.instructions ?? '',
    model: profile.model ?? '',
    escalate_keywords: profile.escalate_keywords.join(', '),
    prompt_blocks: profile.prompt_blocks ?? {},
  }
}

export default function AiAgentProfileEditor() {
  const { profileId } = useParams<{ profileId: string }>()
  const [searchParams] = useSearchParams()
  const token = useAuthStore((state) => state.token)
  const isNew = profileId === 'new'
  const initialRole = (searchParams.get('role') as AgentRole | null) ?? 'planner'

  const [form, setForm] = useState<ProfileForm>(() => emptyForm(isNew ? initialRole : 'planner'))
  const [promptBlockDefs, setPromptBlockDefs] = useState<PromptBlockDefinition[]>([])
  const [loading, setLoading] = useState(!isNew)
  const [notFound, setNotFound] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [leavePrompt, setLeavePrompt] = useState(false)

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])
  const savedSnapshotRef = useRef<string>('')
  const currentSnapshot = useMemo(() => JSON.stringify(form), [form])
  const isDirty = savedSnapshotRef.current !== '' && currentSnapshot !== savedSnapshotRef.current
  const relevance = FIELD_RELEVANCE[form.role]
  const showModelSampling = relevance.model || relevance.temperature || relevance.max_output_tokens
  const showContextBudget =
    relevance.history_limit ||
    relevance.history_channels ||
    relevance.history_lookback_days ||
    relevance.include_beds24 ||
    relevance.include_payments ||
    relevance.include_notes ||
    relevance.include_availability ||
    relevance.include_tenant_brain ||
    relevance.include_brain_index
  const showGuardrails =
    relevance.escalate_keywords ||
    relevance.min_confidence ||
    relevance.on_no_template_match ||
    relevance.max_redraft_attempts ||
    relevance.block_auto_send_on_fail ||
    relevance.match_inbound_language
  const showCost = relevance.daily_token_cap
  const instructionsPlaceholder = INSTRUCTIONS_PLACEHOLDER[form.role]

  useEffect(() => {
    let cancelled = false

    const loadPromptBlocks = async (role: AgentRole) => {
      const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles/prompt-blocks?role=${role}`, {
        headers: authHeaders,
      })
      if (cancelled) return
      setPromptBlockDefs(response.ok ? ((await response.json()) as PromptBlockDefinition[]) : [])
    }

    const load = async () => {
      setMessage('')

      if (isNew) {
        const blank = emptyForm(initialRole)
        setForm(blank)
        savedSnapshotRef.current = JSON.stringify(blank)
        await loadPromptBlocks(initialRole)
        if (!cancelled) setLoading(false)
        return
      }

      if (!profileId) {
        if (!cancelled) setNotFound(true)
        if (!cancelled) setLoading(false)
        return
      }

      const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles/${profileId}`, {
        headers: authHeaders,
      })
      if (cancelled) return
      if (response.status === 404) {
        setNotFound(true)
        setLoading(false)
        return
      }
      if (!response.ok) {
        setMessage('Failed to load profile')
        setLoading(false)
        return
      }
      const data: AiAgentProfile = await response.json()
      const next = toFormState(data)
      setForm(next)
      savedSnapshotRef.current = JSON.stringify(next)
      await loadPromptBlocks(data.role)
      if (!cancelled) setLoading(false)
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [authHeaders, initialRole, isNew, profileId])

  useEffect(() => {
    if (!isDirty) return
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [isDirty])

  const set = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) =>
    setForm((current) => (current ? { ...current, [key]: value } : current))

  const saveProfile = async (): Promise<boolean> => {
    if (!form.name.trim()) {
      setMessage('A name is required')
      return false
    }
    setSaving(true)
    setMessage('')
    try {
      const isEditing = form.id !== null
      const { id, escalate_keywords, model, instructions, ...rest } = form
      const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles${isEditing ? `/${id}` : ''}`, {
        method: isEditing ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          ...rest,
          name: form.name.trim(),
          instructions: instructions.trim() || null,
          model: model.trim() || null,
          escalate_keywords: escalate_keywords
            .split(',')
            .map((word) => word.trim())
            .filter(Boolean),
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setMessage(data?.detail ?? 'Failed to save the profile')
        return false
      }
      setMessage('Saved.')
      const next = toFormState(data)
      setForm(next)
      savedSnapshotRef.current = JSON.stringify(next)
      return true
    } catch {
      setMessage('Failed to save the profile')
      return false
    } finally {
      setSaving(false)
    }
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    await saveProfile()
  }

  const leave = () => window.close()

  const requestLeave = () => {
    if (isDirty) setLeavePrompt(true)
    else leave()
  }

  const saveAndClose = async () => {
    if (await saveProfile()) leave()
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-4xl px-4 py-4">
        <p className="text-sm text-gray-500">Loading...</p>
      </main>
    )
  }

  if (notFound) {
    return (
      <main className="mx-auto max-w-4xl px-4 py-4">
        <p className="text-sm text-rose-600">This profile could not be found. It may have been deleted in another tab.</p>
        <Link to="/settings/ai-agents" className="mt-2 inline-block text-sm text-cyan-700 hover:underline">
          &larr; Back to AI agent profiles
        </Link>
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-4">
      <p className="text-xs">
        <button type="button" onClick={requestLeave} className="text-cyan-700 hover:underline">
          &larr; Back to AI agent profiles
        </button>
      </p>
      <h1 className="mt-1 text-lg font-semibold text-gray-900">
        {form.id !== null ? `Edit ${form.role} profile` : `New ${form.role} profile`}
      </h1>


      <form onSubmit={save} className="mt-4 space-y-3 rounded-2xl border border-gray-200 bg-white p-3.5">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm sm:col-span-2 xl:col-span-2">
            <label className={LABEL} htmlFor="profile-name">
              Name
            </label>
            <input id="profile-name" type="text" value={form.name} onChange={(event) => set('name', event.target.value)} className={INPUT} />
          </div>
          <label className="flex flex-col justify-between rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
            <span className={LABEL}>Default for this role</span>
            <input className="mt-3 h-4 w-4" type="checkbox" checked={form.is_default} onChange={(event) => set('is_default', event.target.checked)} />
          </label>
          <label className="flex flex-col justify-between rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
            <span className={LABEL}>Active</span>
            <input className="mt-3 h-4 w-4" type="checkbox" checked={form.is_active} onChange={(event) => set('is_active', event.target.checked)} />
          </label>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
          <label className={LABEL} htmlFor="profile-instructions">
            Instructions
          </label>
          <textarea
            id="profile-instructions"
            rows={8}
            value={form.instructions}
            onChange={(event) => set('instructions', event.target.value)}
            placeholder={instructionsPlaceholder}
            className={INPUT}
          />
        </div>

        {showModelSampling ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Model &amp; sampling</h3>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {relevance.model ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-model">
                    Model
                  </label>
                  <input
                    id="profile-model"
                    type="text"
                    value={form.model}
                    onChange={(event) => set('model', event.target.value)}
                    placeholder="leave blank for the default"
                    className={INPUT}
                  />
                </div>
              ) : null}
              {relevance.temperature ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-temp">
                    Temperature
                  </label>
                  <input
                    id="profile-temp"
                    type="number"
                    step="0.1"
                    min={0}
                    max={2}
                    value={form.temperature ?? ''}
                    onChange={(event) => set('temperature', event.target.value === '' ? null : Number(event.target.value))}
                    className={INPUT}
                  />
                </div>
              ) : null}
              {relevance.max_output_tokens ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-max-tokens">
                    Max output tokens
                  </label>
                  <input
                    id="profile-max-tokens"
                    type="number"
                    min={1}
                    value={form.max_output_tokens ?? ''}
                    onChange={(event) => set('max_output_tokens', event.target.value === '' ? null : Number(event.target.value))}
                    className={INPUT}
                  />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {showContextBudget ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Context budget</h3>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {relevance.history_limit ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-history">
                    History messages
                  </label>
                  <input
                    id="profile-history"
                    type="number"
                    min={0}
                    value={form.history_limit}
                    onChange={(event) => set('history_limit', Number(event.target.value))}
                    className={INPUT}
                  />
                </div>
              ) : null}
              {relevance.history_channels ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-channels">
                    History channels
                  </label>
                  <select
                    id="profile-channels"
                    value={form.history_channels}
                    onChange={(event) => set('history_channels', event.target.value as ProfileForm['history_channels'])}
                    className={INPUT}
                  >
                    <option value="both">Email + WhatsApp</option>
                    <option value="inbound">Whichever the message arrived on</option>
                    <option value="email">Email only</option>
                    <option value="whatsapp">WhatsApp only</option>
                  </select>
                </div>
              ) : null}
              {relevance.history_lookback_days ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-lookback">
                    Lookback days
                  </label>
                  <input
                    id="profile-lookback"
                    type="number"
                    min={1}
                    value={form.history_lookback_days ?? ''}
                    onChange={(event) => set('history_lookback_days', event.target.value === '' ? null : Number(event.target.value))}
                    placeholder="no limit"
                    className={INPUT}
                  />
                </div>
              ) : null}
              {(relevance.include_beds24 || relevance.include_payments || relevance.include_notes || relevance.include_availability || relevance.include_tenant_brain || relevance.include_brain_index) ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3 sm:col-span-2 xl:col-span-2">
                  <p className={LABEL}>Included sources</p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {relevance.include_beds24 ? (
                      <label className="flex items-center gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={form.include_beds24} onChange={(event) => set('include_beds24', event.target.checked)} />
                        Booking info
                      </label>
                    ) : null}
                    {relevance.include_payments ? (
                      <label className="flex items-center gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={form.include_payments} onChange={(event) => set('include_payments', event.target.checked)} />
                        Payments &amp; charges
                      </label>
                    ) : null}
                    {relevance.include_notes ? (
                      <label className="flex items-center gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={form.include_notes} onChange={(event) => set('include_notes', event.target.checked)} />
                        Internal notes
                      </label>
                    ) : null}
                    {relevance.include_availability ? (
                      <label className="flex items-center gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={form.include_availability} onChange={(event) => set('include_availability', event.target.checked)} />
                        Availability summary
                      </label>
                    ) : null}
                    {relevance.include_tenant_brain ? (
                      <label className="flex items-center gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={form.include_tenant_brain} onChange={(event) => set('include_tenant_brain', event.target.checked)} />
                        Tenant brain (fields &amp; entries)
                      </label>
                    ) : null}
                    {relevance.include_brain_index ? (
                      <label className="flex items-center gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={form.include_brain_index} onChange={(event) => set('include_brain_index', event.target.checked)} />{' '}
                        {form.role === 'planner' ? 'Brain index' : 'Knowledge base'}
                      </label>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {showGuardrails ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Guardrails &amp; escalation</h3>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {relevance.escalate_keywords ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3 sm:col-span-2 xl:col-span-2">
                  <label className={LABEL} htmlFor="profile-keywords">
                    Escalation keywords
                  </label>
                  <input
                    id="profile-keywords"
                    type="text"
                    value={form.escalate_keywords}
                    onChange={(event) => set('escalate_keywords', event.target.value)}
                    placeholder="refund, lawyer, police"
                    className={INPUT}
                  />
                  <p className="mt-1 text-xs text-gray-500">Comma separated. Matches park the conversation for a human before the model runs.</p>
                </div>
              ) : null}
              {relevance.min_confidence ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-min-conf">
                    Minimum confidence
                  </label>
                  <input
                    id="profile-min-conf"
                    type="number"
                    step="0.05"
                    min={0}
                    max={1}
                    value={form.min_confidence}
                    onChange={(event) => set('min_confidence', Number(event.target.value))}
                    className={INPUT}
                  />
                </div>
              ) : null}
              {relevance.on_no_template_match ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-no-match">
                    When no template fits
                  </label>
                  <select
                    id="profile-no-match"
                    value={form.on_no_template_match}
                    onChange={(event) => set('on_no_template_match', event.target.value as ProfileForm['on_no_template_match'])}
                    className={INPUT}
                  >
                    <option value="escalate">Park it for a human</option>
                    <option value="skip">Do nothing</option>
                  </select>
                </div>
              ) : null}
              {relevance.max_redraft_attempts ? (
                <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                  <label className={LABEL} htmlFor="profile-redrafts">
                    Max redrafts
                  </label>
                  <input
                    id="profile-redrafts"
                    type="number"
                    min={0}
                    max={5}
                    value={form.max_redraft_attempts}
                    onChange={(event) => set('max_redraft_attempts', Number(event.target.value))}
                    className={INPUT}
                  />
                  <p className="mt-1 text-xs text-gray-500">After this many rejections the draft is parked for review.</p>
                </div>
              ) : null}
              {relevance.block_auto_send_on_fail ? (
                <label className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={form.block_auto_send_on_fail}
                    onChange={(event) => set('block_auto_send_on_fail', event.target.checked)}
                  />
                  Never auto-send a draft I rejected
                </label>
              ) : null}
              {relevance.match_inbound_language ? (
                <label className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={form.match_inbound_language}
                    onChange={(event) => set('match_inbound_language', event.target.checked)}
                  />
                  Reply in the guest's language
                </label>
              ) : null}
            </div>
          </div>
        ) : null}

        {showCost ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
            <h3 className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Cost</h3>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <label className={LABEL} htmlFor="profile-cap">
                  Daily token cap
                </label>
                <input
                  id="profile-cap"
                  type="number"
                  min={1}
                  value={form.daily_token_cap ?? ''}
                  onChange={(event) => set('daily_token_cap', event.target.value === '' ? null : Number(event.target.value))}
                  placeholder="unlimited"
                  className={INPUT}
                />
              </div>
            </div>
          </div>
        ) : null}

        {promptBlockDefs.length > 0 ? (
          <div className="space-y-2">
            <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
              <h3 className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Prompt blocks</h3>
              <p className="mt-2 text-xs text-gray-500">
                Every fixed piece of wording this agent sends to the model. Leave a box blank to remove that block from the prompt entirely.
              </p>
            </div>
            {form.role !== 'drafter' ? (
              <p className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                The "Output" block text can change, but the field names it mentions are enforced in code.
              </p>
            ) : null}

            {(['structure', 'context'] as const).map((group) => {
              const defs = promptBlockDefs.filter((def) => def.group === group)
              if (!defs.length) return null
              return (
                <div key={group} className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gray-400">
                    {group === 'structure' ? 'Structure' : 'Context headings'}
                  </p>
                  <div className="mt-3 space-y-3">
                    {defs.map((def) => {
                      const value = form.prompt_blocks[def.key] ?? def.default
                      const isDefault = !(def.key in form.prompt_blocks)
                      return (
                        <div key={def.key} className="rounded-2xl border border-gray-200 bg-gray-50 p-3">
                          <div className="flex items-center justify-between gap-3">
                            <label className={LABEL} htmlFor={`block-${def.key}`}>
                              {def.label}
                            </label>
                            {isDefault ? null : (
                              <button
                                type="button"
                                onClick={() =>
                                  setForm((current) => {
                                    if (!current) return current
                                    const { [def.key]: _removed, ...rest } = current.prompt_blocks
                                    return { ...current, prompt_blocks: rest }
                                  })
                                }
                                className="shrink-0 text-xs font-semibold text-cyan-700 hover:underline"
                              >
                                Reset to default
                              </button>
                            )}
                          </div>
                          <textarea
                            id={`block-${def.key}`}
                            rows={value.split('\n').length > 2 ? 4 : 2}
                            value={value}
                            onChange={(event) => {
                              const next = event.target.value
                              setForm((current) =>
                                current ? { ...current, prompt_blocks: { ...current.prompt_blocks, [def.key]: next } } : current,
                              )
                            }}
                            className={`${INPUT} font-mono text-xs`}
                          />
                          <p className="mt-1 text-xs text-gray-500">{def.help}</p>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={saveAndClose}
            className="rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-2 text-sm font-semibold text-cyan-700 hover:bg-cyan-100 disabled:bg-gray-100 disabled:text-gray-400"
          >
            {saving ? 'Saving...' : 'Save & Close'}
          </button>
          <button
            type="button"
            onClick={requestLeave}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          {message ? <p className="text-sm text-gray-600">{message}</p> : null}
        </div>
      </form>
      {leavePrompt ? (
        <div
          role="alertdialog"
          aria-label="Unsaved profile changes"
          className="fixed inset-0 z-[100] flex items-center justify-center bg-white/60 p-4 backdrop-blur-md"
        >
          <div className="flex w-full max-w-sm flex-col items-center gap-3 rounded-xl bg-white p-5 text-center shadow-xl">
            <p className="text-lg font-semibold text-gray-800">Unsaved changes</p>
            <p className="text-sm text-gray-500">This profile has changes that have not been saved.</p>
            <div className="flex w-full flex-col gap-2">
              <button
                type="button"
                disabled={saving}
                onClick={async () => {
                  if (await saveProfile()) leave()
                  else setLeavePrompt(false)
                }}
                className="w-full rounded-xl bg-cyan-600 px-4 py-2.5 font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? 'Saving...' : 'Save & Leave'}
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={leave}
                className="w-full rounded-xl border border-rose-200 bg-white px-4 py-2.5 font-semibold text-rose-600 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Discard &amp; Leave
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={() => setLeavePrompt(false)}
                className="w-full rounded-xl border border-gray-300 px-4 py-2.5 font-semibold text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  )
}
