import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { useToast } from '../lib/useToast'
import ToastHost from '../components/Toast'
import SettingsSidebarLayout, { SettingsTab } from '../components/settings/SettingsSidebarLayout'
import WorkingMemoryCanvas from '../components/WorkingMemoryCanvas'
import { CARD_HEIGHT, CARD_WIDTH, nextCardPosition, type WorkingMemoryCard } from '../lib/workingMemoryCanvas'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

const TABS: SettingsTab[] = [
  { id: 'rules', label: 'Rules' },
  { id: 'fields', label: 'Field Schema' },
  { id: 'suggestions', label: 'Pending Suggestions' },
  { id: 'redo-log', label: 'Redo Log' },
]

function slugify(value: string) {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'field'
  )
}

type WorkingMemoryRule = { id: number; condition_text: string; action_text: string; status: string; source: string }

function useAuthHeaders() {
  const token = useAuthStore((state) => state.token)
  return token ? { Authorization: `Bearer ${token}` } : undefined
}

// -------------------------------------------------------------------------------- Rules tab

function RulesTab({ showSuccess, showError }: { showSuccess: (m: string) => void; showError: (m: string) => void }) {
  const authHeaders = useAuthHeaders()
  const [cards, setCards] = useState<WorkingMemoryCard[]>([])
  const [pending, setPending] = useState<WorkingMemoryRule[]>([])
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const baselineRef = useRef<Map<number, { primary: string; secondary: string }>>(new Map())

  const load = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/working-memory-rules`, { headers: authHeaders })
      if (!response.ok) throw new Error()
      const all: WorkingMemoryRule[] = await response.json()
      const active = all.filter((rule) => rule.status === 'active')
      setPending(all.filter((rule) => rule.status === 'pending_approval'))
      setCards(
        active.map((rule, index) => ({
          id: String(rule.id),
          serverId: rule.id,
          primary: rule.condition_text,
          secondary: rule.action_text,
          status: rule.status,
          w: CARD_WIDTH,
          h: CARD_HEIGHT,
          ...nextCardPosition(index),
          z: index,
        })),
      )
      baselineRef.current = new Map(active.map((rule) => [rule.id, { primary: rule.condition_text, secondary: rule.action_text }]))
    } catch {
      showError('Failed to load rules')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      const currentServerIds = new Set(cards.filter((card) => card.serverId !== null).map((card) => card.serverId))
      for (const id of baselineRef.current.keys()) {
        if (!currentServerIds.has(id)) {
          await fetch(`${API_BASE_URL}/api/working-memory-rules/${id}`, { method: 'DELETE', headers: authHeaders })
        }
      }
      for (const card of cards) {
        if (!card.primary.trim() || !card.secondary.trim()) continue
        if (card.serverId === null) {
          await fetch(`${API_BASE_URL}/api/working-memory-rules`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
            body: JSON.stringify({ condition_text: card.primary, action_text: card.secondary }),
          })
        } else {
          const baseline = baselineRef.current.get(card.serverId)
          if (baseline && (baseline.primary !== card.primary || baseline.secondary !== card.secondary)) {
            await fetch(`${API_BASE_URL}/api/working-memory-rules/${card.serverId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
              body: JSON.stringify({ condition_text: card.primary, action_text: card.secondary }),
            })
          }
        }
      }
      showSuccess('Rules saved')
      await load()
    } catch {
      showError('Failed to save rules')
    } finally {
      setSaving(false)
    }
  }

  const reviewRule = async (id: number, action: 'approve' | 'reject') => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/working-memory-rules/${id}/${action}`, { method: 'POST', headers: authHeaders })
      if (!response.ok) throw new Error()
      showSuccess(action === 'approve' ? 'Rule approved' : 'Rule dismissed')
      await load()
    } catch {
      showError(`Failed to ${action} rule`)
    }
  }

  return (
    <section className="space-y-4">
      {pending.length > 0 ? (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-3.5">
          <h3 className="text-sm font-semibold text-amber-900">Pending AI-suggested rules</h3>
          <div className="mt-2 space-y-2">
            {pending.map((rule) => (
              <div key={rule.id} className="rounded-xl border border-amber-200 bg-white p-2.5 text-sm">
                <p className="text-gray-900">
                  <span className="font-semibold">If</span> {rule.condition_text} <span className="font-semibold">then</span> {rule.action_text}
                </p>
                <div className="mt-1.5 flex gap-2">
                  <button type="button" onClick={() => reviewRule(rule.id, 'approve')} className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                    Approve
                  </button>
                  <button type="button" onClick={() => reviewRule(rule.id, 'reject')} className="rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-500">
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rounded-2xl border border-gray-200 bg-white p-3.5">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">If This Then That Rules</h2>
            <p className="mt-1 text-sm text-gray-500">
              Plain condition/action text, not a structured builder - handed to the AI as-is whenever rules are wired into a
              drafting prompt (not yet in this build).
            </p>
          </div>
          <button type="button" onClick={save} disabled={saving} className="shrink-0 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300">
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
        {loading ? (
          <p className="mt-3 text-sm text-gray-500">Loading...</p>
        ) : (
          <div className="mt-3">
            <WorkingMemoryCanvas
              cards={cards}
              onCardsChange={setCards}
              primaryLabel="Condition"
              primaryPlaceholder="e.g. Returning customer"
              secondaryLabel="Action"
              secondaryPlaceholder="e.g. Always offer a discount"
              addButtonLabel="+ Rule"
              viewportKey="working-memory-rules"
            />
          </div>
        )}
      </div>
    </section>
  )
}

// -------------------------------------------------------------------------------- Fields tab

type BrainFieldDefinition = { id: number; key: string; label: string; ai_instruction: string; is_active: boolean }

function FieldsTab({ showSuccess, showError }: { showSuccess: (m: string) => void; showError: (m: string) => void }) {
  const authHeaders = useAuthHeaders()
  const [cards, setCards] = useState<WorkingMemoryCard[]>([])
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const baselineRef = useRef<Map<number, { primary: string; secondary: string; key: string }>>(new Map())

  const load = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/brain-fields`, { headers: authHeaders })
      if (!response.ok) throw new Error()
      const all: BrainFieldDefinition[] = await response.json()
      const active = all.filter((field) => field.is_active)
      setCards(
        active.map((field, index) => ({
          id: String(field.id),
          serverId: field.id,
          primary: field.label,
          secondary: field.ai_instruction,
          w: CARD_WIDTH,
          h: CARD_HEIGHT,
          ...nextCardPosition(index),
          z: index,
        })),
      )
      baselineRef.current = new Map(active.map((field) => [field.id, { primary: field.label, secondary: field.ai_instruction, key: field.key }]))
    } catch {
      showError('Failed to load field schema')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      const currentServerIds = new Set(cards.filter((card) => card.serverId !== null).map((card) => card.serverId))
      for (const id of baselineRef.current.keys()) {
        if (!currentServerIds.has(id)) {
          await fetch(`${API_BASE_URL}/api/brain-fields/${id}`, { method: 'DELETE', headers: authHeaders })
        }
      }
      for (const card of cards) {
        if (!card.primary.trim() || !card.secondary.trim()) continue
        if (card.serverId === null) {
          const response = await fetch(`${API_BASE_URL}/api/brain-fields`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
            body: JSON.stringify({ key: slugify(card.primary), label: card.primary, ai_instruction: card.secondary }),
          })
          if (!response.ok) {
            const data = await response.json().catch(() => null)
            showError(data?.detail ?? `Failed to create field "${card.primary}"`)
          }
        } else {
          const baseline = baselineRef.current.get(card.serverId)
          if (baseline && (baseline.primary !== card.primary || baseline.secondary !== card.secondary)) {
            await fetch(`${API_BASE_URL}/api/brain-fields/${card.serverId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
              body: JSON.stringify({ label: card.primary, ai_instruction: card.secondary }),
            })
          }
        }
      }
      showSuccess('Field schema saved')
      await load()
    } catch {
      showError('Failed to save field schema')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Structured Brain Fields</h2>
          <p className="mt-1 text-sm text-gray-500">
            One global schema, tried against every tenant. Each field's instruction tells the brain writer what evidence
            to look for - it only fills a field when the tenant's messages/history actually support it.
          </p>
        </div>
        <button type="button" onClick={save} disabled={saving} className="shrink-0 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300">
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
      {loading ? (
        <p className="mt-3 text-sm text-gray-500">Loading...</p>
      ) : (
        <div className="mt-3">
          <WorkingMemoryCanvas
            cards={cards}
            onCardsChange={setCards}
            primaryLabel="Field Name"
            primaryPlaceholder="e.g. Pet ownership"
            secondaryLabel="AI Instruction"
            secondaryPlaceholder="e.g. Note whether the tenant mentions having pets."
            addButtonLabel="+ Field"
            viewportKey="working-memory-fields"
          />
        </div>
      )}
    </section>
  )
}

// -------------------------------------------------------------------------------- Suggestions tab

type MemorySuggestion = {
  id: number
  kind: string
  tenant_id: number | null
  tenant_name: string | null
  proposed_value: Record<string, unknown>
  reasoning: string | null
  created_at: string
}

function describeSuggestion(suggestion: MemorySuggestion): string {
  const value = suggestion.proposed_value
  switch (suggestion.kind) {
    case 'field_value':
      return `Set field "${value.field_key}" to "${value.value}"`
    case 'brain_entry':
      return `Add brain entry: "${value.content}"`
    case 'rule_add':
      return `Add rule: if ${value.condition_text} then ${value.action_text}`
    case 'rule_modify':
      return `Modify rule #${value.rule_id}: ${value.condition_text ?? ''} ${value.action_text ?? ''}`.trim()
    case 'rule_delete':
      return `Dismiss rule #${value.rule_id}`
    default:
      return suggestion.kind
  }
}

function SuggestionsTab({ showSuccess, showError }: { showSuccess: (m: string) => void; showError: (m: string) => void }) {
  const authHeaders = useAuthHeaders()
  const [suggestions, setSuggestions] = useState<MemorySuggestion[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/memory-suggestions`, { headers: authHeaders })
      if (!response.ok) throw new Error()
      setSuggestions(await response.json())
    } catch {
      showError('Failed to load pending suggestions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const review = async (id: number, action: 'approve' | 'reject') => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/memory-suggestions/${id}/${action}`, { method: 'POST', headers: authHeaders })
      const data = await response.json().catch(() => null)
      if (!response.ok) throw new Error()
      showSuccess(data?.message ?? 'Done')
      await load()
    } catch {
      showError(`Failed to ${action} suggestion`)
    }
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
      <h2 className="text-lg font-semibold text-gray-900">Pending Suggestions</h2>
      <p className="mt-1 text-sm text-gray-500">
        AI-proposed working-memory and rule changes arising from redo feedback. Nothing here applies automatically.
      </p>
      <div className="mt-3 space-y-2">
        {loading ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : suggestions.length === 0 ? (
          <p className="text-sm text-gray-400">Nothing pending.</p>
        ) : (
          suggestions.map((suggestion) => (
            <div key={suggestion.id} className="rounded-xl border border-gray-200 p-2.5 text-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  {suggestion.tenant_name ? <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{suggestion.tenant_name}</p> : null}
                  <p className="text-gray-900">{describeSuggestion(suggestion)}</p>
                  {suggestion.reasoning ? <p className="mt-1 text-xs text-gray-500">{suggestion.reasoning}</p> : null}
                </div>
                <div className="flex shrink-0 gap-2">
                  <button type="button" onClick={() => review(suggestion.id, 'approve')} className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
                    Approve
                  </button>
                  <button type="button" onClick={() => review(suggestion.id, 'reject')} className="rounded-full border border-gray-200 px-2.5 py-0.5 text-xs font-medium text-gray-500">
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  )
}

// -------------------------------------------------------------------------------- Redo log tab

type RedoRequest = {
  id: number
  tenant_name: string | null
  channel: string
  what: string
  why: string | null
  requested_by_email: string | null
  created_at: string
}

function RedoLogTab({ showError }: { showError: (m: string) => void }) {
  const authHeaders = useAuthHeaders()
  const [requests, setRequests] = useState<RedoRequest[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try {
        const response = await fetch(`${API_BASE_URL}/api/redo-requests`, { headers: authHeaders })
        if (!response.ok) throw new Error()
        setRequests(await response.json())
      } catch {
        showError('Failed to load the redo log')
      } finally {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-3.5">
      <h2 className="text-lg font-semibold text-gray-900">Redo Log</h2>
      <p className="mt-1 text-sm text-gray-500">Every redo request, from WhatsApp or the CRM, whether or not it succeeded.</p>
      <div className="mt-3 overflow-x-auto">
        {loading ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <th className="py-1.5">When</th>
                <th>Tenant</th>
                <th>Channel</th>
                <th>What</th>
                <th>Why</th>
                <th>Requested by</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((request) => (
                <tr key={request.id} className="border-t border-gray-100 align-top">
                  <td className="whitespace-nowrap py-2">{new Date(request.created_at).toLocaleString()}</td>
                  <td>{request.tenant_name ?? '-'}</td>
                  <td className="uppercase">{request.channel}</td>
                  <td className="max-w-xs">{request.what}</td>
                  <td className="max-w-xs">{request.why ?? '-'}</td>
                  <td>{request.requested_by_email ?? '-'}</td>
                </tr>
              ))}
              {!requests.length ? (
                <tr>
                  <td colSpan={6} className="py-3 text-center text-gray-400">No redo requests yet</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

// -------------------------------------------------------------------------------- page shell

export default function WorkingMemoryHome() {
  const [activeTab, setActiveTab] = useState('rules')
  const { toast, showSuccess, showError, dismiss } = useToast()

  return (
    <>
      <SettingsSidebarLayout title="Working Memory" subtitle="Rules, structured fields, and AI-suggested changes" tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab}>
        {activeTab === 'rules' ? <RulesTab showSuccess={showSuccess} showError={showError} /> : null}
        {activeTab === 'fields' ? <FieldsTab showSuccess={showSuccess} showError={showError} /> : null}
        {activeTab === 'suggestions' ? <SuggestionsTab showSuccess={showSuccess} showError={showError} /> : null}
        {activeTab === 'redo-log' ? <RedoLogTab showError={showError} /> : null}
      </SettingsSidebarLayout>
      <ToastHost toast={toast} onDismiss={dismiss} />
    </>
  )
}
