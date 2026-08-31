import { apiClient } from './client'

/**
 * Tenant finance (`GET /api/tenants/{id}/finance` in `backend/app/api/tenants.py`).
 *
 * NOTE: the route returns a hand-built dict, NOT the `Finance` pydantic schema — each line item
 * is `{id, type, amount (string), currency, description, created_at}` (see `get_tenant_finance`'s
 * `_fmt`). Charges and payments come pre-split by `type`. Amounts are strings to avoid float drift.
 */

export type FinanceLineItem = {
  id: number
  type: string
  amount: string
  currency: string | null
  description: string | null
  created_at: string
}

export type TenantFinance = {
  tenant: {
    id: number
    booking_id: string
    name: string
    room_name: string | null
    property_name: string | null
    check_in: string | null
    check_out: string | null
  }
  charges: FinanceLineItem[]
  payments: FinanceLineItem[]
}

/** GET /api/tenants/{id}/finance — Beds24 charges + payments for the tenant. Read-only. */
export async function getTenantFinance(tenantId: number): Promise<TenantFinance> {
  const { data } = await apiClient.get<TenantFinance>(`/api/tenants/${tenantId}/finance`)
  return data
}
