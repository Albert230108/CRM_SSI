import { apiClient } from './client'

/**
 * Tenant endpoints (`backend/app/api/tenants.py`, mounted under /api).
 * Types mirror `TenantRead` in `backend/app/schemas/tenant.py`. Only the fields the mobile MVP
 * uses are typed richly; the rest of the booking record is available but omitted for brevity.
 */
export type TenantRead = {
  id: number
  booking_id: string
  name: string
  first_name: string | null
  last_name: string | null
  email: string | null
  phone: string | null
  mobile: string | null
  check_in: string | null
  check_out: string | null
  room_name: string | null
  property_name: string | null
  booking_status: string | null
  responsible_comm: string | null
  created_at: string
  updated_at: string
  // Derived by the list endpoint (latest message + unread rollup per tenant).
  last_message_date: string | null
  last_message_channel: string | null
  last_message_direction: string | null
  unread_count: number
}

/** GET /api/tenants?search=... — server-side ILIKE over name/booking_id/email/phone/mobile. */
export async function listTenants(search?: string): Promise<TenantRead[]> {
  const { data } = await apiClient.get<TenantRead[]>('/api/tenants', {
    params: {
      search: search?.trim() ? search.trim() : undefined,
      // Sort by most-recent message so the on-the-go list surfaces active threads first.
      sort_by_message: true,
      sort_desc: true,
    },
  })
  return data
}

/** GET /api/tenants/{id} */
export async function getTenant(tenantId: number): Promise<TenantRead> {
  const { data } = await apiClient.get<TenantRead>(`/api/tenants/${tenantId}`)
  return data
}
