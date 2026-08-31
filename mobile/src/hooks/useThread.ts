import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  extractEmailThreads,
  flattenThread,
  forwardEmailThread,
  generateAiDraft,
  getGroupedThread,
  getThreadVersion,
  getWhatsappEndpoints,
  sendEmailReply,
  sendWhatsappMessage,
} from '../api/communications'

export const threadKeys = {
  thread: (tenantId: number) => ['thread', tenantId] as const,
  version: (tenantId: number) => ['thread-version', tenantId] as const,
  endpoints: (tenantId: number) => ['whatsapp-endpoints', tenantId] as const,
}

/**
 * A tenant's unified WhatsApp + email timeline, flattened to chronological bubbles plus the email
 * threads available to reply into. `select` keeps the flatten off the render path except when data
 * actually changes. Polling is driven by the cheap thread-version query below (see useThreadPoll),
 * so this query itself doesn't run a full-thread interval.
 */
export function useThread(tenantId: number) {
  return useQuery({
    queryKey: threadKeys.thread(tenantId),
    queryFn: () => getGroupedThread(tenantId),
    select: (data) => ({
      tenantName: data.tenant_name,
      bubbles: flattenThread(data),
      emailThreads: extractEmailThreads(data),
    }),
  })
}

/**
 * Cheap change-marker poll (`/thread-version` → { latest_at }). The screen watches `latest_at` and
 * only refetches the full grouped-thread when it changes — far lighter than polling the whole
 * timeline every few seconds.
 */
export function useThreadVersion(tenantId: number) {
  return useQuery({
    queryKey: threadKeys.version(tenantId),
    queryFn: () => getThreadVersion(tenantId),
    refetchInterval: 10_000,
  })
}

/** Active manual WhatsApp chat links for a tenant — determines whether/where we can send. */
export function useWhatsappEndpoints(tenantId: number) {
  return useQuery({
    queryKey: threadKeys.endpoints(tenantId),
    queryFn: () => getWhatsappEndpoints(tenantId),
  })
}

function useThreadInvalidator(tenantId: number) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: threadKeys.thread(tenantId) })
    void queryClient.invalidateQueries({ queryKey: threadKeys.version(tenantId) })
  }
}

/** Send a plain-text WhatsApp message, then refresh the thread so the outbound bubble appears. */
export function useSendWhatsapp(tenantId: number) {
  const invalidate = useThreadInvalidator(tenantId)
  return useMutation({
    mutationFn: (args: { message: string; whatsappEndpointId: number }) =>
      sendWhatsappMessage({ tenantId, ...args }),
    onSuccess: invalidate,
  })
}

/** Send a plain-text email reply into an existing thread. */
export function useSendEmail(tenantId: number) {
  const invalidate = useThreadInvalidator(tenantId)
  return useMutation({
    mutationFn: (args: { emailThreadId: number; message: string; subject?: string | null }) =>
      sendEmailReply({ tenantId, ...args }),
    onSuccess: invalidate,
  })
}

/** Forward an email thread to the admin-configured forwarding address. */
export function useForwardEmail(tenantId: number) {
  const invalidate = useThreadInvalidator(tenantId)
  return useMutation({
    mutationFn: (args: { emailThreadId: number; body: string }) =>
      forwardEmailThread({ tenantId, ...args }),
    onSuccess: invalidate,
  })
}

/** Generate an AI reply draft (never auto-sent — the caller reviews it in the composer). */
export function useAiDraft(tenantId: number) {
  return useMutation({
    mutationFn: (args: { channel: 'email' | 'whatsapp'; roughDraft?: string }) =>
      generateAiDraft({ tenantId, ...args }),
  })
}
