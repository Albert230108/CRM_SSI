import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export type AgentRole = 'planner' | 'checker'

export type AiAgentProfile = {
  id: number
  name: string
  role: AgentRole
  is_default: boolean
  is_active: boolean
  instructions: string | null
  model: string | null
  temperature: number | null
  max_output_tokens: number | null
  history_limit: number
  history_channels: 'both' | 'inbound' | 'email' | 'whatsapp'
  history_lookback_days: number | null
  include_beds24: boolean
  include_payments: boolean
  include_notes: boolean
  include_brain_index: boolean
  match_inbound_language: boolean
  escalate_keywords: string[]
  on_no_template_match: 'escalate' | 'skip'
  min_confidence: number
  max_redraft_attempts: number
  block_auto_send_on_fail: boolean
  daily_token_cap: number | null
}

// The form keeps the nullable text fields as plain strings so the inputs stay controlled;
// they are converted back to null on save when left blank.
type ProfileForm = Omit<AiAgentProfile, 'id' | 'escalate_keywords' | 'instructions' | 'model'> & {
  id: number | null
  escalate_keywords: string
  instructions: string
  model: string
}

const emptyForm = (role: AgentRole): ProfileForm => ({
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
  include_brain_index: true,
  match_inbound_language: true,
  escalate_keywords: '',
  on_no_template_match: 'escalate',
  min_confidence: 0.5,
  max_redraft_attempts: 2,
  block_auto_send_on_fail: true,
  daily_token_cap: null,
})

const CARD = 'rounded-2xl border border-gray-200 bg-white p-3.5'
const LABEL = 'block text-xs font-semibold uppercase tracking-[0.24em] text-gray-500'
const INPUT =
  'mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500'

export default function AiAgentProfiles() {
  const token = useAuthStore((state) => state.token)
  const [profiles, setProfiles] = useState<AiAgentProfile[]>([])
  const [form, setForm] = useState<ProfileForm | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  const load = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles`, { headers: authHeaders })
    if (response.ok) setProfiles(await response.json())
  }, [authHeaders])

  useEffect(() => {
    void load()
  }, [load])

  const startEdit = (profile: AiAgentProfile) => {
    setMessage('')
    setForm({ ...profile, instructions: profile.instructions ?? '', model: profile.model ?? '', escalate_keywords: profile.escalate_keywords.join(', ') })
  }

  const save = async () => {
    if (!form) return
    if (!form.name.trim()) {
      setMessage('A name is required')
      return
    }
    setSaving(true)
    setMessage('')
    try {
      const isEditing = form.id !== null
      const { id, escalate_keywords, model, instructions, ...rest } = form
      const response = await fetch(
        `${API_BASE_URL}/api/ai-agent-profiles${isEditing ? `/${id}` : ''}`,
        {
          method: isEditing ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({
            ...rest,
            name: form.name.trim(),
            instructions: instructions.trim() || null,
            // An empty model box means "follow the deployment default", not a pinned empty string.
            model: model.trim() || null,
            escalate_keywords: escalate_keywords
              .split(',')
              .map((word) => word.trim())
              .filter(Boolean),
          }),
        },
      )
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setMessage(data?.detail ?? 'Failed to save the profile')
        return
      }
      setForm(null)
      setMessage('Saved')
      await load()
    } finally {
      setSaving(false)
    }
  }

  const remove = async (profile: AiAgentProfile) => {
    if (!window.confirm(`Delete the profile "${profile.name}"?`)) return
    const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles/${profile.id}`, {
      method: 'DELETE',
      headers: authHeaders,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setMessage(data?.detail ?? 'Failed to delete the profile')
      return
    }
    if (form?.id === profile.id) setForm(null)
    await load()
  }

  const set = <K extends keyof ProfileForm>(key: K, value: ProfileForm[K]) =>
    setForm((current) => (current ? { ...current, [key]: value } : current))

  const renderRole = (role: AgentRole, title: string, blurb: string) => (
    <section className={`mt-4 ${CARD}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <p className="mt-1.5 text-sm text-gray-500">{blurb}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setMessage('')
            setForm(emptyForm(role))
          }}
          className="shrink-0 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
        >
          + New {role}
        </button>
      </div>

      <div className="mt-3 space-y-2">
        {profiles
          .filter((profile) => profile.role === role)
          .map((profile) => (
            <div key={profile.id} className="rounded-xl border border-gray-200 p-2.5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-900">
                    {profile.name}
                    {profile.is_default ? (
                      <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">default</span>
                    ) : null}
                    {!profile.is_active ? <span className="ml-2 text-xs text-amber-600">inactive</span> : null}
                  </p>
                  <p className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                    <span className="rounded-full bg-gray-100 px-2 py-0.5">{profile.model || 'default model'}</span>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5">temp {profile.temperature ?? '-'}</span>
                    <span className="rounded-full bg-gray-100 px-2 py-0.5">
                      {profile.history_limit} msgs / {profile.history_channels}
                    </span>
                    {role === 'planner' ? (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5">min conf {profile.min_confidence}</span>
                    ) : (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5">{profile.max_redraft_attempts} redrafts</span>
                    )}
                    {profile.escalate_keywords.length ? (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">
                        {profile.escalate_keywords.length} escalation keyword(s)
                      </span>
                    ) : null}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button type="button" onClick={() => startEdit(profile)} className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700">Edit</button>
                  <button type="button" onClick={() => remove(profile)} className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-600">Delete</button>
                </div>
              </div>
            </div>
          ))}
        {!profiles.some((profile) => profile.role === role) ? (
          <p className="text-sm text-gray-500">No {role} profiles yet. The planner cannot run without one.</p>
        ) : null}
      </div>
    </section>
  )

  return (
    <main className="mx-auto max-w-4xl px-6 py-4">
      <Link to="/settings" className="text-sm text-cyan-700 hover:underline">&larr; Back to Settings</Link>
      <div className="mt-1.5 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Planner &amp; Checker Profiles</h1>
          <p className="mt-1.5 text-sm text-gray-500">
            The planner reads a conversation and decides which template to use and what the reply must cover. The
            checker proof-reads the result and either approves it or sends it back with feedback. One profile per
            role is the default; a tenant can be pinned to a different one on the{' '}
            <Link to="/settings/ai-tenants" className="text-cyan-700 hover:underline">per-tenant page</Link>.
          </p>
        </div>
        <Link
          to="/ai-runs"
          className="shrink-0 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
        >
          View planner runs &rarr;
        </Link>
      </div>

      {renderRole('planner', 'Planner profiles', 'Chooses the template, the knowledge to pull in, and the instruction for the drafter.')}
      {renderRole('checker', 'Checker profiles', 'Reviews each draft. It never rewrites the text itself — it only approves or gives feedback.')}

      {form ? (
        <section className={`mt-4 ${CARD}`}>
          <h2 className="text-lg font-semibold text-gray-900">
            {form.id !== null ? `Edit ${form.role} profile` : `New ${form.role} profile`}
          </h2>

          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label className={LABEL} htmlFor="profile-name">Name</label>
              <input id="profile-name" type="text" value={form.name} onChange={(event) => set('name', event.target.value)} className={INPUT} />
            </div>
            <div className="flex items-end gap-4 pb-1">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={form.is_default} onChange={(event) => set('is_default', event.target.checked)} />
                Default for this role
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={form.is_active} onChange={(event) => set('is_active', event.target.checked)} />
                Active
              </label>
            </div>
          </div>

          <div className="mt-3">
            <label className={LABEL} htmlFor="profile-instructions">Instructions</label>
            <textarea
              id="profile-instructions"
              rows={8}
              value={form.instructions}
              onChange={(event) => set('instructions', event.target.value)}
              placeholder={
                form.role === 'planner'
                  ? 'e.g. Always prefer the most specific template. If the guest asks several things, pick the template covering the most urgent one and mention the rest in the instruction.'
                  : 'e.g. Reject the draft if it invents a price, promises anything not in the knowledge base, or is longer than four sentences.'
              }
              className={INPUT}
            />
          </div>

          <h3 className="mt-4 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Model &amp; sampling</h3>
          <div className="mt-1.5 grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className={LABEL} htmlFor="profile-model">Model</label>
              <input id="profile-model" type="text" value={form.model} onChange={(event) => set('model', event.target.value)} placeholder="leave blank for the default" className={INPUT} />
            </div>
            <div>
              <label className={LABEL} htmlFor="profile-temp">Temperature</label>
              <input id="profile-temp" type="number" step="0.1" min={0} max={2} value={form.temperature ?? ''} onChange={(event) => set('temperature', event.target.value === '' ? null : Number(event.target.value))} className={INPUT} />
            </div>
            <div>
              <label className={LABEL} htmlFor="profile-max-tokens">Max output tokens</label>
              <input id="profile-max-tokens" type="number" min={1} value={form.max_output_tokens ?? ''} onChange={(event) => set('max_output_tokens', event.target.value === '' ? null : Number(event.target.value))} className={INPUT} />
            </div>
          </div>

          <h3 className="mt-4 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Context budget</h3>
          <div className="mt-1.5 grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className={LABEL} htmlFor="profile-history">History messages</label>
              <input id="profile-history" type="number" min={0} value={form.history_limit} onChange={(event) => set('history_limit', Number(event.target.value))} className={INPUT} />
            </div>
            <div>
              <label className={LABEL} htmlFor="profile-channels">History channels</label>
              <select id="profile-channels" value={form.history_channels} onChange={(event) => set('history_channels', event.target.value as ProfileForm['history_channels'])} className={INPUT}>
                <option value="both">Email + WhatsApp</option>
                <option value="inbound">Whichever the message arrived on</option>
                <option value="email">Email only</option>
                <option value="whatsapp">WhatsApp only</option>
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="profile-lookback">Lookback days</label>
              <input id="profile-lookback" type="number" min={1} value={form.history_lookback_days ?? ''} onChange={(event) => set('history_lookback_days', event.target.value === '' ? null : Number(event.target.value))} placeholder="no limit" className={INPUT} />
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={form.include_beds24} onChange={(event) => set('include_beds24', event.target.checked)} /> Booking info
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={form.include_payments} onChange={(event) => set('include_payments', event.target.checked)} /> Payments &amp; charges
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={form.include_notes} onChange={(event) => set('include_notes', event.target.checked)} /> Internal notes
            </label>
            {form.role === 'planner' ? (
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={form.include_brain_index} onChange={(event) => set('include_brain_index', event.target.checked)} /> Brain index
              </label>
            ) : null}
          </div>

          <h3 className="mt-4 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Guardrails &amp; escalation</h3>
          <div className="mt-1.5">
            <label className={LABEL} htmlFor="profile-keywords">Escalation keywords</label>
            <input id="profile-keywords" type="text" value={form.escalate_keywords} onChange={(event) => set('escalate_keywords', event.target.value)} placeholder="refund, lawyer, police" className={INPUT} />
            <p className="mt-1 text-xs text-gray-500">
              Comma separated, case-insensitive. A match parks the conversation for a human before any model is called.
            </p>
          </div>
          <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-3">
            {form.role === 'planner' ? (
              <>
                <div>
                  <label className={LABEL} htmlFor="profile-min-conf">Minimum confidence</label>
                  <input id="profile-min-conf" type="number" step="0.05" min={0} max={1} value={form.min_confidence} onChange={(event) => set('min_confidence', Number(event.target.value))} className={INPUT} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="profile-no-match">When no template fits</label>
                  <select id="profile-no-match" value={form.on_no_template_match} onChange={(event) => set('on_no_template_match', event.target.value as ProfileForm['on_no_template_match'])} className={INPUT}>
                    <option value="escalate">Park it for a human</option>
                    <option value="skip">Do nothing</option>
                  </select>
                </div>
              </>
            ) : (
              <>
                <div>
                  <label className={LABEL} htmlFor="profile-redrafts">Max redrafts</label>
                  <input id="profile-redrafts" type="number" min={0} max={5} value={form.max_redraft_attempts} onChange={(event) => set('max_redraft_attempts', Number(event.target.value))} className={INPUT} />
                  <p className="mt-1 text-xs text-gray-500">After this many rejections the last draft is parked for review.</p>
                </div>
                <label className="flex items-end gap-2 pb-3 text-sm text-gray-700">
                  <input type="checkbox" checked={form.block_auto_send_on_fail} onChange={(event) => set('block_auto_send_on_fail', event.target.checked)} />
                  Never auto-send a draft I rejected
                </label>
              </>
            )}
            <label className="flex items-end gap-2 pb-3 text-sm text-gray-700">
              <input type="checkbox" checked={form.match_inbound_language} onChange={(event) => set('match_inbound_language', event.target.checked)} />
              Reply in the guest's language
            </label>
          </div>

          <h3 className="mt-4 text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">Cost</h3>
          <div className="mt-1.5 max-w-xs">
            <label className={LABEL} htmlFor="profile-cap">Daily token cap</label>
            <input id="profile-cap" type="number" min={1} value={form.daily_token_cap ?? ''} onChange={(event) => set('daily_token_cap', event.target.value === '' ? null : Number(event.target.value))} placeholder="unlimited" className={INPUT} />
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button type="button" onClick={save} disabled={saving} className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300">
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button type="button" onClick={() => setForm(null)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            {message ? <p className="text-sm text-gray-600">{message}</p> : null}
          </div>
        </section>
      ) : message ? (
        <p className="mt-3 text-sm text-gray-600">{message}</p>
      ) : null}
    </main>
  )
}
