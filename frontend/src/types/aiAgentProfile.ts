export type AgentRole = 'planner' | 'checker' | 'drafter' | 'brain_writer' | 'action_writer' | 'memory_redo' | 'memory_qa'

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
  include_availability: boolean
  include_brain_index: boolean
  match_inbound_language: boolean
  escalate_keywords: string[]
  on_no_template_match: 'escalate' | 'skip'
  min_confidence: number
  max_redraft_attempts: number
  block_auto_send_on_fail: boolean
  daily_token_cap: number | null
  // Overrides for the fixed prompt scaffolding. A key absent here uses the built-in default
  // from PromptBlockDefinition.default; a key present with '' removes that block entirely.
  prompt_blocks: Record<string, string>
}

export type PromptBlockDefinition = {
  key: string
  label: string
  help: string
  default: string
  group: 'structure' | 'context'
}
