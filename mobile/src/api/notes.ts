import { apiClient } from './client'

/**
 * Tenant notes (`backend/app/api/tenants.py`). Notes live on the tenant record itself
 * (`tenant.notes` committed, `tenant.draft_notes` in-progress) — so the current values come from
 * `GET /api/tenants/{id}` (TenantRead has `notes` + `draft_notes`), and these endpoints mutate them.
 *
 * A committed save (`PATCH /notes`) also syncs the note to Beds24 and clears any draft; the draft
 * endpoints (`PATCH/DELETE /notes/draft`) never touch Beds24 or the committed note — they mirror
 * the web app's autosave-while-typing behaviour so an unsaved edit survives navigation.
 */

export type NotesSaveResult = {
  notes: string | null
  beds24_synced: boolean
  beds24_error?: string
}

/** PATCH /api/tenants/{id}/notes — commit notes (also syncs to Beds24, clears the draft). */
export async function saveTenantNotes(
  tenantId: number,
  notes: string | null,
): Promise<NotesSaveResult> {
  const { data } = await apiClient.patch<NotesSaveResult>(`/api/tenants/${tenantId}/notes`, {
    notes,
  })
  return data
}

/** PATCH /api/tenants/{id}/notes/draft — persist an uncommitted edit (no Beds24 sync). */
export async function saveTenantDraftNotes(
  tenantId: number,
  draftNotes: string | null,
): Promise<{ draft_notes: string | null }> {
  const { data } = await apiClient.patch<{ draft_notes: string | null }>(
    `/api/tenants/${tenantId}/notes/draft`,
    { draft_notes: draftNotes },
  )
  return data
}

/** DELETE /api/tenants/{id}/notes/draft — discard the uncommitted edit. */
export async function discardTenantDraftNotes(tenantId: number): Promise<void> {
  await apiClient.delete(`/api/tenants/${tenantId}/notes/draft`)
}
