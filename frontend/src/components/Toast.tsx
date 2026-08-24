import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as anime from 'animejs'
import type { ToastState } from '../lib/useToast'

const TOAST_ENTER_OFFSET_PX = 12
const TOAST_EXIT_OFFSET_PX = 8
const TOAST_ENTER_DURATION_MS = 240
const TOAST_EXIT_DURATION_MS = 180
const PREFERS_REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    window.matchMedia(PREFERS_REDUCED_MOTION_QUERY).matches,
  )

  useEffect(() => {
    const mediaQuery = window.matchMedia(PREFERS_REDUCED_MOTION_QUERY)
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches)

    updatePreference()
    mediaQuery.addEventListener('change', updatePreference)
    return () => mediaQuery.removeEventListener('change', updatePreference)
  }, [])

  return prefersReducedMotion
}

type ToastHostProps = {
  toast: ToastState
  onDismiss: () => void
}

export default function ToastHost({ toast, onDismiss }: ToastHostProps) {
  const prefersReducedMotion = usePrefersReducedMotion()
  const toastRef = useRef<HTMLDivElement | null>(null)
  const [renderedToast, setRenderedToast] = useState<ToastState>(toast)
  const [isExiting, setIsExiting] = useState(false)

  useEffect(() => {
    if (toast) {
      setRenderedToast(toast)
      setIsExiting(false)
      return
    }

    if (!renderedToast) return
    if (prefersReducedMotion) {
      setRenderedToast(null)
      return
    }

    const node = toastRef.current
    if (!node) {
      setRenderedToast(null)
      return
    }

    setIsExiting(true)
    anime.remove(node)
    const animation = anime.animate(node, {
      opacity: [1, 0],
      translateY: [0, TOAST_EXIT_OFFSET_PX],
      scale: [1, 0.98],
      duration: TOAST_EXIT_DURATION_MS,
      ease: 'in(2)',
      onComplete: () => setRenderedToast(null),
    })

    return () => {
      animation.revert()
      anime.remove(node)
    }
  }, [prefersReducedMotion, renderedToast, toast])

  useLayoutEffect(() => {
    if (!renderedToast || isExiting) return
    if (prefersReducedMotion) return

    const node = toastRef.current
    if (!node) return

    anime.remove(node)
    node.style.opacity = '0'
    node.style.transform = `translateY(${TOAST_ENTER_OFFSET_PX}px) scale(0.98)`

    const animation = anime.animate(node, {
      opacity: [0, 1],
      translateY: [TOAST_ENTER_OFFSET_PX, 0],
      scale: [0.98, 1],
      duration: TOAST_ENTER_DURATION_MS,
      ease: 'out(2)',
    })

    return () => {
      animation.revert()
      anime.remove(node)
    }
  }, [isExiting, prefersReducedMotion, renderedToast?.id])

  if (!renderedToast) return null

  const tone =
    renderedToast.kind === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : 'border-rose-200 bg-rose-50 text-rose-800'

  return (
    <div
      ref={toastRef}
      className={`fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-lg ${tone}`}
      role="status"
      aria-live="polite"
    >
      <p className="flex-1">{renderedToast.message}</p>
      <button type="button" onClick={onDismiss} className="shrink-0 text-xs font-semibold opacity-70 hover:opacity-100" aria-label="Dismiss">
        &times;
      </button>
    </div>
  )
}
