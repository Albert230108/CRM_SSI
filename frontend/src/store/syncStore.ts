import { create } from 'zustand'

export type SyncProgress = {
  phase?: 'beds24' | 'email' | 'whatsapp' | 'threads'
  phase_index?: number
  phases_total?: number
  current?: number
  total?: number
}

type SyncStore = {
  // Bumped whenever a global sync-all or Beds24 import (triggered from the Navbar)
  // finishes successfully, so any mounted Dashboard instance can react (bump its own
  // local tenant-list reload signal) without Navbar and Dashboard needing a direct
  // parent/child relationship.
  syncCompletedAt: number
  importCompletedAt: number
  // sync-all runs as a backend job that outlives any single request, so the job id lives
  // here rather than in Navbar state: that way navigating between routes (which remounts
  // Navbar) doesn't orphan a run that is still in progress.
  syncJobId: string | null
  syncProgress: SyncProgress
  notifySyncCompleted: () => void
  notifyImportCompleted: () => void
  setSyncJob: (jobId: string | null) => void
  setSyncProgress: (progress: SyncProgress) => void
}

export const useSyncStore = create<SyncStore>((set) => ({
  syncCompletedAt: 0,
  importCompletedAt: 0,
  syncJobId: null,
  syncProgress: {},
  notifySyncCompleted: () => set({ syncCompletedAt: Date.now() }),
  notifyImportCompleted: () => set({ importCompletedAt: Date.now() }),
  setSyncJob: (jobId) => set({ syncJobId: jobId, syncProgress: {} }),
  setSyncProgress: (progress) => set({ syncProgress: progress }),
}))
