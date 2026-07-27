import { useEffect, useRef, useState } from 'react'

type SyncProgressOverlayProps = {
  active: boolean
}

// Estimated progress only (no backend job/progress reporting exists for sync-all).
// Eases toward 90% while the request is in flight, then snaps to 100% once it resolves.
const EASE_TIME_CONSTANT_MS = 4000
const COMPLETE_HOLD_MS = 500

export default function SyncProgressOverlay({ active }: SyncProgressOverlayProps) {
  const [visible, setVisible] = useState(false)
  const [progress, setProgress] = useState(0)
  const wasActiveRef = useRef(false)

  useEffect(() => {
    if (active && !wasActiveRef.current) {
      wasActiveRef.current = true
      setVisible(true)
      setProgress(0)
      const startedAt = Date.now()
      const intervalId = window.setInterval(() => {
        const elapsed = Date.now() - startedAt
        setProgress(90 * (1 - Math.exp(-elapsed / EASE_TIME_CONSTANT_MS)))
      }, 150)
      return () => window.clearInterval(intervalId)
    }

    if (!active && wasActiveRef.current) {
      wasActiveRef.current = false
      setProgress(100)
      const timeoutId = window.setTimeout(() => setVisible(false), COMPLETE_HOLD_MS)
      return () => window.clearTimeout(timeoutId)
    }
  }, [active])

  if (!visible) return null

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Syncing data"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-white/60 backdrop-blur-md"
    >
      <span className="h-12 w-12 animate-spin rounded-full border-4 border-cyan-600 border-t-transparent" />
      <p className="text-lg font-semibold text-gray-800">Syncing... {Math.round(progress)}%</p>
    </div>
  )
}
