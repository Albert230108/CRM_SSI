import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import * as anime from 'animejs'

type ToastTone = 'success' | 'error' | 'info'

type ToastCardProps = {
  toastKey: number | string
  tone: ToastTone
  durationMs: number
  children: ReactNode
  className?: string
}

const TONE_CLASSES: Record<ToastTone, { card: string; bar: string; fill: string }> = {
  success: { card: 'border-emerald-200 bg-emerald-50 text-emerald-900', bar: 'bg-emerald-200', fill: 'bg-emerald-500' },
  error: { card: 'border-rose-200 bg-rose-50 text-rose-900', bar: 'bg-rose-200', fill: 'bg-rose-500' },
  info: { card: 'border-cyan-200 bg-cyan-50 text-cyan-900', bar: 'bg-cyan-200', fill: 'bg-cyan-500' },
}

const TOAST_CARD_ENTER_OFFSET_PX = 12
const TOAST_CARD_ENTER_DURATION_MS = 240
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

export default function ToastCard({ toastKey, tone, durationMs, children, className = 'w-80' }: ToastCardProps) {
  const classes = TONE_CLASSES[tone]
  const prefersReducedMotion = usePrefersReducedMotion()
  const cardRef = useRef<HTMLDivElement | null>(null)

  useLayoutEffect(() => {
    if (prefersReducedMotion) return

    const node = cardRef.current
    if (!node) return

    anime.remove(node)
    node.style.opacity = '0'
    node.style.transform = `translateY(${TOAST_CARD_ENTER_OFFSET_PX}px) scale(0.98)`

    const animation = anime.animate(node, {
      opacity: [0, 1],
      translateY: [TOAST_CARD_ENTER_OFFSET_PX, 0],
      scale: [0.98, 1],
      duration: TOAST_CARD_ENTER_DURATION_MS,
      ease: 'out(2)',
    })

    return () => {
      animation.revert()
      anime.remove(node)
    }
  }, [prefersReducedMotion, toastKey])

  return (
    <div ref={cardRef} className={[className, 'overflow-hidden rounded-2xl border shadow-lg', classes.card].join(' ')}>
      <div className="px-4 py-3 text-sm">{children}</div>
      <div className={['h-1 w-full', classes.bar].join(' ')}>
        <div
          key={toastKey}
          className={['h-full animate-toast-countdown', classes.fill].join(' ')}
          style={{ animationDuration: `${durationMs}ms` }}
        />
      </div>
    </div>
  )
}
