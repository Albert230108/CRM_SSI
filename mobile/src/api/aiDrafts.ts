import { apiClient } from './client'

/**
 * AI auto-drafts queue (`backend/app/api/ai_auto_drafts.py`, router prefix /ai-auto-drafts →
 * /api/ai-auto-drafts). These are AI-generated reply drafts awaiting a human decision. Mutating
 * actions are PUTs that return the updated draft; `redo` additionally needs a `what` instruction.
 */

export type AiAutoDraft = {
  id: number
  tenant_id: number
  tenant_name: string | null
  channel: string
  template_id: number | null
  generated_text: string
  formatted_text: string | null
  quoted_context: string | null
  status: string
  scheduled_send_at: string | null
  created_at: string
}

/** GET /api/ai-auto-drafts — defaults to the actionable statuses server-side. */
export async function listAiAutoDrafts(): Promise<AiAutoDraft[]> {
  const { data } = await apiClient.get<AiAutoDraft[]>('/api/ai-auto-drafts')
  return data
}

async function draftAction(draftId: number, action: string): Promise<AiAutoDraft> {
  const { data } = await apiClient.put<AiAutoDraft>(`/api/ai-auto-drafts/${draftId}/${action}`)
  return data
}

/** PUT /api/ai-auto-drafts/{id}/send-now — send the draft immediately. */
export const sendAiAutoDraftNow = (id: number) => draftAction(id, 'send-now')
/** PUT /api/ai-auto-drafts/{id}/dismiss — discard the draft. */
export const dismissAiAutoDraft = (id: number) => draftAction(id, 'dismiss')
/** PUT /api/ai-auto-drafts/{id}/cancel-auto-send — stop a scheduled auto-send (back to pending). */
export const cancelAiAutoDraftSend = (id: number) => draftAction(id, 'cancel-auto-send')
/** PUT /api/ai-auto-drafts/{id}/mark-used — mark as used as a manual seed. */
export const markAiAutoDraftUsed = (id: number) => draftAction(id, 'mark-used')

/** PUT /api/ai-auto-drafts/{id}/redo — regenerate with an instruction (`what` is required). */
export async function redoAiAutoDraft(id: number, what: string): Promise<AiAutoDraft> {
  const { data } = await apiClient.put<AiAutoDraft>(`/api/ai-auto-drafts/${id}/redo`, { what })
  return data
}
