import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getTenantFinance } from '../api/finance'
import {
  createBrainEntry,
  deleteBrainEntry,
  getBrainEntries,
  updateBrainEntry,
} from '../api/brain'
import { discardTenantDraftNotes, saveTenantDraftNotes, saveTenantNotes } from '../api/notes'
import { tenantKeys } from './useTenants'

/**
 * Data hooks for the tenant detail screen: finance, notes (commit/draft), and brain entries.
 * Notes mutations invalidate the tenant detail query (`tenantKeys.detail`) since `notes`/
 * `draft_notes` live on the tenant record returned by `GET /api/tenants/{id}`.
 */

export const tenantDetailKeys = {
  finance: (id: number) => ['tenant-finance', id] as const,
  brain: (id: number) => ['tenant-brain', id] as const,
}

export function useTenantFinance(tenantId: number) {
  return useQuery({
    queryKey: tenantDetailKeys.finance(tenantId),
    queryFn: () => getTenantFinance(tenantId),
  })
}

/** Commit tenant notes (also syncs to Beds24 server-side). Refreshes the tenant detail after. */
export function useSaveNotes(tenantId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (notes: string | null) => saveTenantNotes(tenantId, notes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tenantKeys.detail(tenantId) })
    },
  })
}

/** Autosave an uncommitted notes edit (no Beds24 sync). */
export function useSaveDraftNotes(tenantId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (draftNotes: string | null) => saveTenantDraftNotes(tenantId, draftNotes),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tenantKeys.detail(tenantId) })
    },
  })
}

/** Discard the uncommitted notes draft. */
export function useDiscardDraftNotes(tenantId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => discardTenantDraftNotes(tenantId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tenantKeys.detail(tenantId) })
    },
  })
}

export function useTenantBrain(tenantId: number) {
  return useQuery({
    queryKey: tenantDetailKeys.brain(tenantId),
    queryFn: () => getBrainEntries(tenantId),
  })
}

export function useCreateBrainEntry(tenantId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (content: string) => createBrainEntry(tenantId, content),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tenantDetailKeys.brain(tenantId) })
    },
  })
}

export function useUpdateBrainEntry(tenantId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: { entryId: number; content: string }) =>
      updateBrainEntry(tenantId, args.entryId, args.content),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tenantDetailKeys.brain(tenantId) })
    },
  })
}

export function useDeleteBrainEntry(tenantId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (entryId: number) => deleteBrainEntry(tenantId, entryId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: tenantDetailKeys.brain(tenantId) })
    },
  })
}
