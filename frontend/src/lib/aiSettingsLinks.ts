export type AiSettingsLink = {
  to: string
  label: string
  description: string
}

export const aiSettingsLinks: readonly AiSettingsLink[] = [
  { to: '/settings/ai-templates', label: 'AI Templates', description: 'Manage the shared reply templates used by Draft with AI.' },
  { to: '/settings/brain', label: 'AI Brain', description: 'Browse shared knowledge sections and tokens.' },
  { to: '/settings/ai-agents', label: 'Agent Profiles', description: 'Planner, checker, drafter, brain writer, and more.' },
  { to: '/ai-runs', label: 'Planner Runs', description: 'Inspect the planner / drafter / checker logs.' },
  { to: '/settings/ai-tenants', label: 'Tenant AI Settings', description: 'Tune defaults and per-tenant AI behavior.' },
]
