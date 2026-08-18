import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import AiTemplateSectionCanvas, { nextSectionPosition } from '../components/AiTemplateSectionCanvas'
import type { AiReplyTemplate, AiTemplateNote, AiTemplateSection, BrainSectionOption } from '../types/aiReplyTemplate'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

const EMAIL_TEMPLATE_PLACEHOLDERS = [
  'tenant_name', 'first_name', 'last_name', 'email', 'phone', 'check_in', 'check_out',
  'num_nights', 'num_adults', 'num_children', 'room_name', 'property_name', 'booking_id',
  'booking_status', 'language', 'arrival_time', 'departure_time', 'city', 'country',
]

type FormState = {
  id: number | null
  name: string
  description: string
  guidelines: string
  sections: AiTemplateSection[]
  canvas_notes: AiTemplateNote[]
  brain_section_ids: number[]
  include_history: boolean
  history_message_limit: number | null
  include_beds24: boolean
  include_payments: boolean
  include_notes: boolean
}

const emptyForm: FormState = {
  id: null,
  name: '',
  description: '',
  guidelines: '',
  sections: [{ id: crypto.randomUUID(), label: '', content: '', order: 0, ...nextSectionPosition(0) }],
  canvas_notes: [],
  brain_section_ids: [],
  include_history: false,
  history_message_limit: 20,
  include_beds24: false,
  include_payments: false,
  include_notes: false,
}

function backfillSections(sections: AiTemplateSection[]): AiTemplateSection[] {
  return sections.map((section, index) => {
    const position = section.x != null && section.y != null ? { x: section.x, y: section.y } : nextSectionPosition(index)
    return {
      ...section,
      id: section.id ?? crypto.randomUUID(),
      order: section.order ?? index,
      x: position.x,
      y: position.y,
    }
  })
}

function toFormState(template: AiReplyTemplate): FormState {
  return {
    id: template.id,
    name: template.name,
    description: template.description ?? '',
    guidelines: template.guidelines ?? '',
    sections: backfillSections(template.sections.length ? template.sections : [{ label: '', content: '' }]),
    canvas_notes: template.canvas_notes ?? [],
    brain_section_ids: template.brain_section_ids ?? [],
    include_history: template.include_history,
    history_message_limit: template.history_message_limit ?? 20,
    include_beds24: template.include_beds24,
    include_payments: template.include_payments,
    include_notes: template.include_notes,
  }
}

export default function AiTemplateEditor() {
  const { templateId } = useParams<{ templateId: string }>()
  const navigate = useNavigate()
  const token = useAuthStore((state) => state.token)
  const isNew = templateId === 'new'

  const [form, setForm] = useState<FormState>(emptyForm)
  const [brainSections, setBrainSections] = useState<BrainSectionOption[]>([])
  const [loading, setLoading] = useState(!isNew)
  const [notFound, setNotFound] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const loadBrainSections = async () => {
      const response = await fetch(`${API_BASE_URL}/api/brain-sections/flat`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) setBrainSections(await response.json())
    }
    loadBrainSections()
  }, [token])

  useEffect(() => {
    if (isNew) {
      setForm(emptyForm)
      setLoading(false)
      return
    }
    let cancelled = false
    const loadTemplate = async () => {
      setLoading(true)
      const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates/${templateId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (cancelled) return
      if (!response.ok) {
        setNotFound(true)
        setLoading(false)
        return
      }
      const data: AiReplyTemplate = await response.json()
      setForm(toFormState(data))
      setLoading(false)
    }
    loadTemplate()
    return () => {
      cancelled = true
    }
  }, [templateId, isNew, token])

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setMessage('')
    setSaving(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates${form.id !== null ? `/${form.id}` : ''}`, {
        method: form.id !== null ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          name: form.name.trim(),
          description: form.description.trim() || null,
          guidelines: form.guidelines.trim() || null,
          sections: [...form.sections]
            .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
            .filter((section) => section.label.trim() || section.content.trim()),
          canvas_notes: form.canvas_notes.filter((note) => note.text.trim()),
          brain_section_ids: form.brain_section_ids,
          include_history: form.include_history,
          history_message_limit: form.include_history ? form.history_message_limit : null,
          include_beds24: form.include_beds24,
          include_payments: form.include_payments,
          include_notes: form.include_notes,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setMessage(data?.detail ?? 'Failed to save template')
        return
      }
      setMessage('Saved.')
      setForm(toFormState(data))
      if (form.id === null) navigate(`/settings/ai-templates/${data.id}`, { replace: true })
    } catch {
      setMessage('Failed to save template')
    } finally {
      setSaving(false)
    }
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
        <p className="text-sm text-rose-600">This template could not be found. It may have been deleted in another tab.</p>
        <Link to="/settings/ai-templates" className="mt-2 inline-block text-sm text-cyan-700 hover:underline">&larr; Back to templates</Link>
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-4">
      <p className="text-xs">
        <Link to="/settings/ai-templates" className="text-cyan-700 hover:underline">&larr; All templates</Link>
      </p>
      <h1 className="mt-1 text-lg font-semibold text-gray-900">{form.id !== null ? `Edit: ${form.name || 'Untitled template'}` : 'New template'}</h1>
      <p className="mt-1 text-sm text-gray-500">
        The payload sent to Gemini always follows this fixed order:
      </p>
      <p className="mt-1.5 flex flex-wrap gap-2 text-xs font-semibold text-gray-600">
        <span className="rounded-full bg-gray-100 px-2 py-0.5">0. Goal &amp; Guidelines</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5">1. Template text</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5">1b. Knowledge base (brain)</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5">2. Message history</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5">3. Beds24 info (booking + payments + notes)</span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5">4. Your typed reply</span>
      </p>

      <form onSubmit={save} className="mt-3 space-y-3 rounded-2xl border border-gray-200 bg-white p-3.5">
        <input
          type="text"
          value={form.name}
          onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
          placeholder="Template name"
          required
          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
        />

        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">When to use this template</p>
          <textarea
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
            placeholder="e.g. Use when a guest asks to arrive outside normal check-in hours."
            rows={2}
            className="w-full resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
          />
          <p className="text-xs text-gray-500">
            Read by the planner when it picks a template. It is never sent to the drafting model, so describe the
            situation rather than writing instructions here.
          </p>
        </div>

        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">0. Goal &amp; Guidelines</p>
          <textarea
            value={form.guidelines}
            onChange={(event) => setForm((current) => ({ ...current, guidelines: event.target.value }))}
            placeholder="Describe this template's goal, e.g. Used for late check-in requests; keep replies under 3 sentences."
            rows={2}
            className="w-full resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none placeholder:text-gray-500 focus:border-cyan-500"
          />
          <p className="text-xs text-gray-500">
            Supports placeholders: {EMAIL_TEMPLATE_PLACEHOLDERS.map((token) => `{{${token}}}`).join(', ')}
          </p>
          <p className="text-xs text-gray-500">
            Brain references also work here and in every section below, e.g.{' '}
            <code className="rounded bg-white px-1 py-0.5">{'{{brain:policies.cancellation}}'}</code>.
          </p>
        </div>

        <AiTemplateSectionCanvas
          sections={form.sections}
          notes={form.canvas_notes}
          onSectionsChange={(sections) => setForm((current) => ({ ...current, sections }))}
          onNotesChange={(canvas_notes) => setForm((current) => ({ ...current, canvas_notes }))}
          contentPlaceholderHint="Section content, e.g. You are a friendly host responding on behalf of..."
        />
        <p className="text-xs text-gray-500">
          Supports placeholders: {EMAIL_TEMPLATE_PLACEHOLDERS.map((token) => `{{${token}}}`).join(', ')}
        </p>

        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">1b. Knowledge base (brain sections)</p>
          {brainSections.length === 0 ? (
            <p className="text-xs text-gray-500">
              No brain sections yet. <Link to="/settings/brain" className="text-cyan-700 hover:underline">Create some</Link> to
              share knowledge across templates.
            </p>
          ) : (
            <div className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2">
              {brainSections.map((section) => (
                <label key={section.id} className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={form.brain_section_ids.includes(section.id)}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        brain_section_ids: event.target.checked
                          ? [...current.brain_section_ids, section.id]
                          : current.brain_section_ids.filter((id) => id !== section.id),
                      }))
                    }
                    className="h-4 w-4 rounded border-gray-300"
                  />
                  <span className="truncate">
                    {section.title}
                    {!section.is_active ? <span className="ml-2 text-xs text-amber-600">inactive</span> : null}
                    <span className="ml-2 font-mono text-xs text-gray-400">{section.path}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
          <p className="text-xs text-gray-500">
            Attached sections are appended as their own block, including everything nested under them. Use an inline{' '}
            <code className="rounded bg-white px-1 py-0.5">{'{{brain:path}}'}</code> token instead when the text needs
            to land at a specific spot.
          </p>
        </div>

        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">2. Message history</p>
          <label className="flex items-center gap-3 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.include_history}
              onChange={(event) => setForm((current) => ({ ...current, include_history: event.target.checked }))}
              className="h-4 w-4 rounded border-gray-300"
            />
            Include conversation history, last
            <input
              type="number"
              min={1}
              value={form.history_message_limit ?? ''}
              onChange={(event) => setForm((current) => ({ ...current, history_message_limit: event.target.value ? Number(event.target.value) : null }))}
              disabled={!form.include_history}
              className="w-20 rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 outline-none disabled:cursor-not-allowed disabled:bg-gray-100"
            />
            messages (email + WhatsApp combined)
          </label>
        </div>

        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">3. Beds24 info (booking + payments + notes)</p>
          <label className="flex items-center gap-3 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.include_beds24}
              onChange={(event) => setForm((current) => ({ ...current, include_beds24: event.target.checked }))}
              className="h-4 w-4 rounded border-gray-300"
            />
            Include Beds24 booking info
          </label>
          <label className="flex items-center gap-3 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.include_payments}
              onChange={(event) => setForm((current) => ({ ...current, include_payments: event.target.checked }))}
              className="h-4 w-4 rounded border-gray-300"
            />
            Include payments/charges
          </label>
          <label className="flex items-center gap-3 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={form.include_notes}
              onChange={(event) => setForm((current) => ({ ...current, include_notes: event.target.checked }))}
              className="h-4 w-4 rounded border-gray-300"
            />
            Include tenant notes
          </label>
        </div>

        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-gray-500">4. Your typed reply (sent automatically when you use "Draft with AI")</p>

        <div className="flex items-center gap-2">
          <button type="submit" disabled={saving} className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:bg-gray-300">
            {saving ? 'Saving...' : form.id !== null ? 'Save changes' : 'Create template'}
          </button>
          {message ? <p className="text-sm text-gray-600">{message}</p> : null}
        </div>
      </form>
    </main>
  )
}
