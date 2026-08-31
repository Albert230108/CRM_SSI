import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  completeActionItem,
  createActionItem,
  dismissActionItem,
  listActionItems,
  parseActionItem,
  reopenActionItem,
} from '../api/actions'

export const actionKeys = {
  list: (status: string) => ['action-items', status] as const,
}

/** Action items list, optionally filtered by status ('' = all). Polls in the foreground. */
export function useActionItems(status = '') {
  return useQuery({
    queryKey: actionKeys.list(status),
    queryFn: () => listActionItems(status),
    refetchInterval: 30_000,
  })
}

function useActionMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['action-items'] })
    },
  })
}

export const useCompleteAction = () => useActionMutation((id: number) => completeActionItem(id))
export const useDismissAction = () => useActionMutation((id: number) => dismissActionItem(id))
export const useReopenAction = () => useActionMutation((id: number) => reopenActionItem(id))

/**
 * Quick-add: try to parse the text into a structured task (title/due/priority/tags); if parsing
 * fails, fall back to creating a plain task from the raw text so the user never loses their input.
 */
export function useQuickAddAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (text: string) => {
      const trimmed = text.trim()
      try {
        const parsed = await parseActionItem(trimmed)
        return await createActionItem({
          title: parsed.title,
          due_date: parsed.due_date,
          priority: parsed.priority,
          tag_ids: parsed.tag_ids,
        })
      } catch {
        // Parsing is best-effort (LLM-backed); never block task creation on it.
        return createActionItem({ title: trimmed })
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['action-items'] })
    },
  })
}
