import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import * as anime from 'animejs'
import type { ToastState } from '../lib/useToast'

export type ToastTone = 'success' | 'error' | 'info'

const TONE_CLASSES: Record<ToastTone, { card: string; bar: string; fill: string }> = {
  success: { card: 'border-emerald-200 bg-emerald-50 text-emerald-900', bar: 'bg-emerald-200', fill: 'bg-emerald-500' },
  error: { card: 'border-rose-200 bg-rose-50 text-rose-900', bar: 'bg-rose-200', fill: 'bg-rose-500' },
  info: { card: 'border-cyan-200 bg-cyan-50 text-cyan-900', bar: 'bg-cyan-200', fill: 'bg-cyan-500' },
}

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

function getToastHost() {
  const existing = document.getElementById('crm-toast-host')
  if (existing) return existing
  const host = document.createElement('div')
  host.id = 'crm-toast-host'
  host.className = 'fixed right-4 top-20 z-[110] flex w-[min(32rem,calc(100vw-2rem))] flex-col gap-2'
  document.body.appendChild(host)
  return host
}

export function ToastStack({ children }: { children: ReactNode }) {
  return createPortal(children, getToastHost())
}

export function ToastCard({
  toastKey,
  tone,
  durationMs,
  children,
  className = 'w-full',
}: {
  toastKey: number | string
  tone: ToastTone
  durationMs: number
  children: ReactNode
  className?: string
}) {
  const classes = TONE_CLASSES[tone]
  const prefersReducedMotion = usePrefersReducedMotion()
  const cardRef = useRef<HTMLDivElement | null>(null)

  useLayoutEffect(() => {
    if (prefersReducedMotion || !cardRef.current) return
    const node = cardRef.current
    anime.remove(node)
    node.style.opacity = '0'
    node.style.transform = 'translateY(12px) scale(0.98)'
    const animation = anime.animate(node, {
      opacity: [0, 1],
      translateY: [12, 0],
      scale: [0.98, 1],
      duration: 240,
      ease: 'out(2)',
    })
    return () => {
      animation.revert()
      anime.remove(node)
    }
  }, [prefersReducedMotion, toastKey])

  return (
    <div ref={cardRef} className={`${className} overflow-hidden rounded-xl border shadow-lg ${classes.card}`} role="status" aria-live="polite">
      <div className="px-4 py-3 text-sm">{children}</div>
      <div className={`h-1 w-full ${classes.bar}`}>
        <div key={toastKey} className={`h-full animate-toast-countdown ${classes.fill}`} style={{ animationDuration: `${durationMs}ms` }} />
      </div>
    </div>
  )
}

export default function ToastHost({ toast, onDismiss }: { toast: ToastState; onDismiss: () => void }) {
  if (!toast) return null
  return (
    <ToastStack>
      <ToastCard toastKey={toast.id} tone={toast.kind} durationMs={4000}>
        <div className="flex items-start gap-3">
          <p className="flex-1">{toast.message}</p>
          <button type="button" onClick={onDismiss} className="shrink-0 text-xs font-semibold opacity-70 hover:opacity-100" aria-label="Dismiss">
            &times;
          </button>
        </div>
      </ToastCard>
    </ToastStack>
  )
}
