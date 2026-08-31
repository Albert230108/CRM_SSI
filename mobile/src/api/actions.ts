import { apiClient } from './client'

/**
 * Action items — tasks/to-dos (`backend/app/api/action_items.py`, mounted under /api). Quick-add
 * uses the NL parse endpoint to extract a title/due date/priority, then creates the item.
 */

export type ActionTag = { id: number; name: string; color: string | null }

export type ActionItem = {
  id: number
  tenant_id: number | null
  tenant_name: string | null
  title: string
  description: string | null
  due_date: string | null
  due_time: string | null
  status: string
  source: string
  tags: ActionTag[]
  priority: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export type ParsedActionItem = {
  title: string
  due_date: string | null
  priority: string | null
  tag_ids: number[]
}

/** GET /api/action-items — all items (optionally filtered by status). Done items sort last. */
export async function listActionItems(status?: string): Promise<ActionItem[]> {
  const { data } = await apiClient.get<ActionItem[]>('/api/action-items', {
    params: { status: status || undefined },
  })
  return data
}

/** POST /api/action-items/parse — NL text → {title, due_date, priority, tag_ids}. */
export async function parseActionItem(text: string): Promise<ParsedActionItem> {
  const { data } = await apiClient.post<ParsedActionItem>('/api/action-items/parse', { text })
  return data
}

/** POST /api/action-items — create a task. */
export async function createActionItem(payload: {
  title: string
  due_date?: string | null
  priority?: string | null
  tag_ids?: number[]
}): Promise<ActionItem> {
  const { data } = await apiClient.post<ActionItem>('/api/action-items', {
    title: payload.title,
    due_date: payload.due_date ?? undefined,
    priority: payload.priority ?? undefined,
    tag_ids: payload.tag_ids ?? [],
  })
  return data
}

async function itemAction(id: number, action: string): Promise<ActionItem> {
  const { data } = await apiClient.post<ActionItem>(`/api/action-items/${id}/${action}`)
  return data
}

/** POST /api/action-items/{id}/complete */
export const completeActionItem = (id: number) => itemAction(id, 'complete')
/** POST /api/action-items/{id}/dismiss */
export const dismissActionItem = (id: number) => itemAction(id, 'dismiss')
/** POST /api/action-items/{id}/reopen */
export const reopenActionItem = (id: number) => itemAction(id, 'reopen')
