import { create } from 'zustand'

type NotesDraftHandlers = {
  tenantId: number
  save: () => Promise<void>
  discard: () => void
  flushDraft: () => void
}

type PendingNavigation = {
  proceed: () => void
}

type NotesDraftState = {
  isDirty: boolean
  handlers: NotesDraftHandlers | null
  pending: PendingNavigation | null
  registerHandlers: (handlers: NotesDraftHandlers) => void
  clearHandlers: (tenantId: number) => void
  setDirty: (tenantId: number, dirty: boolean) => void
  guardNavigation: (proceed: () => void) => void
  resolvePending: (choice: 'save' | 'discard' | 'cancel') => Promise<boolean>
}

export const useNotesDraftStore = create<NotesDraftState>((set, get) => ({
  isDirty: false,
  handlers: null,
  pending: null,

  registerHandlers: (handlers) => set({ handlers }),

  clearHandlers: (tenantId) =>
    set((state) => (state.handlers?.tenantId === tenantId ? { handlers: null, isDirty: false } : state)),

  setDirty: (tenantId, dirty) =>
    set((state) => (state.handlers?.tenantId === tenantId ? { isDirty: dirty } : state)),

  guardNavigation: (proceed) => {
    if (!get().isDirty) {
      proceed()
      return
    }
    set({ pending: { proceed } })
  },

  resolvePending: async (choice) => {
    const { pending, handlers } = get()
    if (!pending) return true

    if (choice === 'cancel') {
      set({ pending: null })
      return true
    }

    if (choice === 'save') {
      try {
        await handlers?.save()
      } catch {
        return false
      }
    } else {
      handlers?.discard()
    }

    set({ pending: null, isDirty: false })
    pending.proceed()
    return true
  },
}))
