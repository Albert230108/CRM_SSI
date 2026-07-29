import { create } from 'zustand'

type SyncStore = {
  // Bumped whenever a global sync-all or Beds24 import (triggered from the Navbar)
  // finishes successfully, so any mounted Dashboard instance can react (bump its own
  // local tenant-list reload signal) without Navbar and Dashboard needing a direct
  // parent/child relationship.
  syncCompletedAt: number
  importCompletedAt: number
  notifySyncCompleted: () => void
  notifyImportCompleted: () => void
}

export const useSyncStore = create<SyncStore>((set) => ({
  syncCompletedAt: 0,
  importCompletedAt: 0,
  notifySyncCompleted: () => set({ syncCompletedAt: Date.now() }),
  notifyImportCompleted: () => set({ importCompletedAt: Date.now() }),
}))
