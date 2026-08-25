import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { getAiSettingsReturnHref } from '../lib/aiSettingsNavigation'
import { type AgentRole, type AiAgentProfile } from '../types/aiAgentProfile'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const CARD = 'rounded-2xl border border-gray-200 bg-white p-3.5'

export default function AiAgentProfiles() {
  useDocumentTitle('CRM - AI Agents')
  const token = useAuthStore((state) => state.token)
  const location = useLocation()
  const [profiles, setProfiles] = useState<AiAgentProfile[]>([])
  const [message, setMessage] = useState('')

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  const load = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles`, { headers: authHeaders })
    if (response.ok) setProfiles(await response.json())
  }, [authHeaders])

  useEffect(() => {
    void load()
  }, [load])

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
    await load()
  }

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
            window.open(`/settings/ai-agents/new?role=${role}`, '_blank')
          }}
          className="shrink-0 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
        >
          + New {role}
        </button>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {profiles
          .filter((profile) => profile.role === role)
          .map((profile) => (
            <div key={profile.id} className="flex h-full flex-col rounded-xl border border-gray-200 p-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900">
                  {profile.name}
                  {profile.is_default ? (
                    <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">default</span>
                  ) : null}
                  {!profile.is_active ? <span className="ml-2 text-xs text-amber-600">inactive</span> : null}
                </p>
                <p className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
                  {role === 'drafter' ? null : (
                    <>
                      <span className="rounded-full bg-gray-100 px-2 py-0.5">{profile.model || 'default model'}</span>
                      <span className="rounded-full bg-gray-100 px-2 py-0.5">temp {profile.temperature ?? '-'}</span>
                      <span className="rounded-full bg-gray-100 px-2 py-0.5">
                        {profile.history_limit} msgs / {profile.history_channels}
                      </span>
                      {role === 'planner' ? (
                        <span className="rounded-full bg-gray-100 px-2 py-0.5">min conf {profile.min_confidence}</span>
                      ) : role === 'checker' ? (
                        <span className="rounded-full bg-gray-100 px-2 py-0.5">{profile.max_redraft_attempts} redrafts</span>
                      ) : null}
                      {profile.escalate_keywords.length ? (
                        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">
                          {profile.escalate_keywords.length} escalation keyword(s)
                        </span>
                      ) : null}
                    </>
                  )}
                  {Object.keys(profile.prompt_blocks).length ? (
                    <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-indigo-700">
                      {Object.keys(profile.prompt_blocks).length} prompt block override(s)
                    </span>
                  ) : null}
                </p>
              </div>
              <div className="mt-auto flex items-center gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => window.open(`/settings/ai-agents/${profile.id}`, '_blank')}
                  className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-50"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => remove(profile)}
                  className="rounded-lg border border-rose-200 px-3 py-1 text-xs font-semibold text-rose-600"
                >
                  Delete
                </button>
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
    <main className="mx-auto max-w-6xl px-6 py-4">
      <Link to={getAiSettingsReturnHref(location.search, '/settings')} className="text-sm text-cyan-700 hover:underline">
        &larr; Back to Settings
      </Link>
      <div className="mt-1.5 flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">AI Agent Profiles</h1>
          <p className="mt-1.5 text-sm text-gray-500">
            The planner reads a conversation and decides which template to use and what the reply must cover. The
            checker proof-reads the result and either approves it or sends it back with feedback. One profile per
            role is the default; a tenant can be pinned to a different one on the{' '}
            <Link to="/settings/ai-tenants" className="text-cyan-700 hover:underline">
              per-tenant page
            </Link>
            .
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
      {renderRole('drafter', 'Drafter profiles', 'Writes the reply itself. Prompt text only — model, sampling and context still come from the reply template.')}
      {renderRole('brain_writer', 'Brain writer profiles', 'Decides, independently of the planner, whether a message is worth remembering long-term for a tenant.')}
      {renderRole('action_writer', 'Action writer profiles', 'Decides, independently of the planner and brain writer, whether a tenant’s action-item list needs a new task or a change to an existing one.')}
      {renderRole('memory_qa', 'Memory QA profiles', 'Answers ad-hoc tenant questions using the context you choose below.')}
      {renderRole('memory_redo', 'Redo log agent profiles', 'Reads redo logs and suggests durable rule changes for review.')}

      {message ? <p className="mt-3 text-sm text-gray-600">{message}</p> : null}
    </main>
  )
}
