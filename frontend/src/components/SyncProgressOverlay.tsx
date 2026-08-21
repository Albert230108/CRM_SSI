import { useEffect, useRef, useState } from 'react'
import type { SyncProgress } from '../store/syncStore'

type SyncProgressOverlayProps = {
  active: boolean
  progress?: SyncProgress
  onDismiss?: () => void
}

// How long a run may go without finishing before the overlay offers a way out. A normal full
// sync is ~2 minutes; past this the run is far more likely wedged than slow, and the overlay
// covers the entire viewport, so there has to be an escape that isn't "reload the tab".
const STUCK_AFTER_MS = 5 * 60 * 1000

const COMPLETE_HOLD_MS = 500

const PHASE_LABELS: Record<string, string> = {
  beds24: 'Updating bookings',
  email: 'Importing emails',
  whatsapp: 'Syncing WhatsApp',
  threads: 'Rebuilding timelines',
}

// The backend reports which of the four phases is running, and item counts for the phases
// that have them. Phases are treated as equal-width slices; within a phase the item counter
// fills that slice, so the bar advances during the long phases instead of sitting still.
function computePercent(progress: SyncProgress | undefined): number {
  if (!progress?.phase_index || !progress.phases_total) return 0
  const sliceWidth = 100 / progress.phases_total
  const completedSlices = (progress.phase_index - 1) * sliceWidth
  const total = progress.total ?? 0
  const withinSlice = total > 0 ? (Math.min(progress.current ?? 0, total) / total) * sliceWidth : 0
  return Math.min(99, completedSlices + withinSlice)
}

export default function SyncProgressOverlay({ active, progress, onDismiss }: SyncProgressOverlayProps) {
  const [visible, setVisible] = useState(false)
  const [displayPercent, setDisplayPercent] = useState(0)
  const [stuck, setStuck] = useState(false)
  const wasActiveRef = useRef(false)

  useEffect(() => {
    if (!active) {
      setStuck(false)
      return
    }
    const timeoutId = window.setTimeout(() => setStuck(true), STUCK_AFTER_MS)
    return () => window.clearTimeout(timeoutId)
  }, [active])

  useEffect(() => {
    if (active && !wasActiveRef.current) {
      wasActiveRef.current = true
      setVisible(true)
      setDisplayPercent(0)
      return
    }

    if (!active && wasActiveRef.current) {
      wasActiveRef.current = false
      setDisplayPercent(100)
      const timeoutId = window.setTimeout(() => setVisible(false), COMPLETE_HOLD_MS)
      return () => window.clearTimeout(timeoutId)
    }
  }, [active])

  useEffect(() => {
    if (!active) return
    // Never let the bar go backwards: phases report independent counters, and a new phase
    // starting at current=0 would otherwise visibly reset it.
    const next = computePercent(progress)
    setDisplayPercent((current) => (next > current ? next : current))
  }, [active, progress])

  if (!visible) return null

  const phaseLabel = progress?.phase ? PHASE_LABELS[progress.phase] ?? 'Syncing' : 'Syncing'
  const counter =
    progress?.total && progress.total > 0 ? ` (${progress.current ?? 0}/${progress.total})` : ''

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Syncing data"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-white/60 backdrop-blur-md"
    >
      <span className="h-12 w-12 animate-spin rounded-full border-4 border-cyan-600 border-t-transparent" />
      <p className="text-lg font-semibold text-gray-800">
        {phaseLabel}
        {counter}... {Math.round(displayPercent)}%
      </p>
      {progress?.phase_index && progress.phases_total ? (
        <p className="text-sm text-gray-600">
          Step {progress.phase_index} of {progress.phases_total}
        </p>
      ) : null}
      {stuck && onDismiss ? (
        <div className="flex flex-col items-center gap-2">
          <p className="text-sm text-gray-600">This sync is taking longer than expected.</p>
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Stop waiting
          </button>
        </div>
      ) : null}
    </div>
  )
}
