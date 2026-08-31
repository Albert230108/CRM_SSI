import { useQuery } from '@tanstack/react-query'

import { getTenant, listTenants } from '../api/tenants'

/** Query keys for tenant data, so mutations elsewhere can invalidate consistently. */
export const tenantKeys = {
  list: (search: string) => ['tenants', search] as const,
  detail: (id: number) => ['tenant', id] as const,
}

/** Tenant list with server-side search. Polls in the foreground to surface new activity. */
export function useTenants(search: string) {
  return useQuery({
    queryKey: tenantKeys.list(search),
    queryFn: () => listTenants(search),
    refetchInterval: 20_000,
  })
}

export function useTenant(tenantId: number) {
  return useQuery({
    queryKey: tenantKeys.detail(tenantId),
    queryFn: () => getTenant(tenantId),
  })
}
