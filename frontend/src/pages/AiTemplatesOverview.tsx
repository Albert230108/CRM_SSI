import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import type { AiReplyTemplate } from '../types/aiReplyTemplate'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export default function AiTemplatesOverview() {
  const token = useAuthStore((state) => state.token)
  const [templates, setTemplates] = useState<AiReplyTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  const loadTemplates = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (response.ok) setTemplates(await response.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTemplates()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openEditor = (templateId: number | 'new') => {
    window.open(`/settings/ai-templates/${templateId}`, '_blank')
  }

  const deleteTemplate = async (templateId: number) => {
    if (!window.confirm('Delete this template? This cannot be undone.')) return
    const response = await fetch(`${API_BASE_URL}/api/ai-reply-templates/${templateId}`, {
      method: 'DELETE',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    })
    if (response.ok) {
      setMessage('')
      await loadTemplates()
    } else {
      setMessage('Failed to delete template')
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs">
            <Link to="/settings" className="text-cyan-700 hover:underline">&larr; Settings</Link>
          </p>
          <h1 className="mt-1 text-lg font-semibold text-gray-900">Shared AI Reply Templates</h1>
          <p className="mt-1 text-sm text-gray-500">
            Templates used by "Draft with AI" in the reply box, shared across all users. Click Edit to open a template in
            its own tab &mdash; you can have several open at once.
          </p>
        </div>
        <button
          type="button"
          onClick={() => openEditor('new')}
          className="shrink-0 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700"
        >
          + New template
        </button>
      </div>

      {message ? <p className="mt-3 text-sm text-rose-600">{message}</p> : null}

      <div className="mt-4 overflow-x-auto rounded-2xl border border-gray-200 bg-white">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-xs font-semibold uppercase tracking-wide text-gray-500">
              <th className="px-3.5 py-2.5">Name</th>
              <th className="px-3.5 py-2.5">Sections</th>
              <th className="px-3.5 py-2.5">Includes</th>
              <th className="px-3.5 py-2.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {templates.map((template) => (
              <tr key={template.id} className="border-b border-gray-100 last:border-b-0 hover:bg-gray-50">
                <td className="px-3.5 py-2.5">
                  <p className="font-semibold text-gray-900">{template.name}</p>
                  {template.description ? <p className="mt-0.5 truncate text-xs text-gray-500">{template.description}</p> : null}
                </td>
                <td className="px-3.5 py-2.5 text-gray-700">
                  {template.sections.length} section{template.sections.length === 1 ? '' : 's'}
                </td>
                <td className="px-3.5 py-2.5">
                  <div className="flex flex-wrap gap-1.5">
                    {template.brain_section_ids?.length ? (
                      <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{template.brain_section_ids.length} brain</span>
                    ) : null}
                    {template.include_history ? <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">History</span> : null}
                    {template.include_beds24 ? <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">Beds24</span> : null}
                    {template.include_payments ? <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">Payments</span> : null}
                    {template.include_notes ? <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">Notes</span> : null}
                    {template.canvas_notes?.length ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">{template.canvas_notes.length} post-it</span> : null}
                  </div>
                </td>
                <td className="px-3.5 py-2.5 text-right">
                  <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => openEditor(template.id)} className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50">
                      Edit
                    </button>
                    <button type="button" onClick={() => deleteTemplate(template.id)} className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-600 hover:bg-rose-50">
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !templates.length ? <p className="p-4 text-sm text-gray-500">No AI templates yet.</p> : null}
        {loading ? <p className="p-4 text-sm text-gray-500">Loading...</p> : null}
      </div>
    </main>
  )
}
