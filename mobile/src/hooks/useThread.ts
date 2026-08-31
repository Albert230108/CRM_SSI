import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  flattenThread,
  getGroupedThread,
  getWhatsappEndpoints,
  sendWhatsappMessage,
} from '../api/communications'

export const threadKeys = {
  thread: (tenantId: number) => ['thread', tenantId] as const,
  endpoints: (tenantId: number) => ['whatsapp-endpoints', tenantId] as const,
}

/**
 * A tenant's unified WhatsApp + email timeline, flattened to chronological bubbles. Polls while
 * foregrounded (the RN stand-in for the web ThreadView's setInterval refresh). `select` keeps the
 * flatten off the render path except when data actually changes.
 */
export function useThread(tenantId: number) {
  return useQuery({
    queryKey: threadKeys.thread(tenantId),
    queryFn: () => getGroupedThread(tenantId),
    refetchInterval: 10_000,
    select: (data) => ({ tenantName: data.tenant_name, bubbles: flattenThread(data) }),
  })
}

/** Active manual WhatsApp chat links for a tenant — determines whether/where we can send. */
export function useWhatsappEndpoints(tenantId: number) {
  return useQuery({
    queryKey: threadKeys.endpoints(tenantId),
    queryFn: () => getWhatsappEndpoints(tenantId),
  })
}

/** Send a plain-text WhatsApp message, then refresh the thread so the outbound bubble appears. */
export function useSendWhatsapp(tenantId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: { message: string; whatsappEndpointId: number }) =>
      sendWhatsappMessage({ tenantId, ...args }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: threadKeys.thread(tenantId) })
    },
  })
}
