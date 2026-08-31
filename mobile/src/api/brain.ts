import { apiClient } from './client'

/**
 * Tenant "brain" — structured per-tenant memory entries (`backend/app/api/tenants.py`,
 * `TenantBrainEntryRead`). Manual add/edit/delete are supported here; the AI `POST .../brain/scan`
 * prefill is deferred to a later phase.
 */

export type BrainEntry = {
  id: number
  content: string
  source: string
  created_by_user_id: number | null
  created_by_email: string | null
  created_at: string
  updated_at: string
}

/** GET /api/tenants/{id}/brain — newest first. */
export async function getBrainEntries(tenantId: number): Promise<BrainEntry[]> {
  const { data } = await apiClient.get<BrainEntry[]>(`/api/tenants/${tenantId}/brain`)
  return data
}

/** POST /api/tenants/{id}/brain — add a manual entry. */
export async function createBrainEntry(tenantId: number, content: string): Promise<BrainEntry> {
  const { data } = await apiClient.post<BrainEntry>(`/api/tenants/${tenantId}/brain`, { content })
  return data
}

/** PATCH /api/tenants/{id}/brain/{entryId} — edit an entry's content. */
export async function updateBrainEntry(
  tenantId: number,
  entryId: number,
  content: string,
): Promise<BrainEntry> {
  const { data } = await apiClient.patch<BrainEntry>(
    `/api/tenants/${tenantId}/brain/${entryId}`,
    { content },
  )
  return data
}

/** DELETE /api/tenants/{id}/brain/{entryId} — remove an entry (204). */
export async function deleteBrainEntry(tenantId: number, entryId: number): Promise<void> {
  await apiClient.delete(`/api/tenants/${tenantId}/brain/${entryId}`)
}
