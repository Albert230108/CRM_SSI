import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  cancelAiAutoDraftSend,
  dismissAiAutoDraft,
  listAiAutoDrafts,
  markAiAutoDraftUsed,
  redoAiAutoDraft,
  sendAiAutoDraftNow,
} from '../api/aiDrafts'

export const aiDraftKeys = {
  list: ['ai-auto-drafts'] as const,
}

/** The AI auto-drafts queue. Polls in the foreground so newly generated drafts appear. */
export function useAiDrafts() {
  return useQuery({
    queryKey: aiDraftKeys.list,
    queryFn: () => listAiAutoDrafts(),
    refetchInterval: 20_000,
  })
}

/** Wrap a draft action so the queue refreshes once the status changes. */
function useDraftMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aiDraftKeys.list })
    },
  })
}

export const useSendDraftNow = () => useDraftMutation((id: number) => sendAiAutoDraftNow(id))
export const useDismissDraft = () => useDraftMutation((id: number) => dismissAiAutoDraft(id))
export const useCancelDraftAutoSend = () =>
  useDraftMutation((id: number) => cancelAiAutoDraftSend(id))
export const useMarkDraftUsed = () => useDraftMutation((id: number) => markAiAutoDraftUsed(id))
export const useRedoDraft = () =>
  useDraftMutation((args: { id: number; what: string }) => redoAiAutoDraft(args.id, args.what))
