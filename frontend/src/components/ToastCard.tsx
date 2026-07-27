import type { ReactNode } from 'react'

type ToastTone = 'success' | 'error' | 'info'

type ToastCardProps = {
  toastKey: number | string
  tone: ToastTone
  durationMs: number
  children: ReactNode
}

const TONE_CLASSES: Record<ToastTone, { card: string; bar: string; fill: string }> = {
  success: { card: 'border-emerald-200 bg-emerald-50 text-emerald-900', bar: 'bg-emerald-200', fill: 'bg-emerald-500' },
  error: { card: 'border-rose-200 bg-rose-50 text-rose-900', bar: 'bg-rose-200', fill: 'bg-rose-500' },
  info: { card: 'border-cyan-200 bg-cyan-50 text-cyan-900', bar: 'bg-cyan-200', fill: 'bg-cyan-500' },
}

export default function ToastCard({ toastKey, tone, durationMs, children }: ToastCardProps) {
  const classes = TONE_CLASSES[tone]

  return (
    <div className={['w-80 overflow-hidden rounded-2xl border shadow-lg', classes.card].join(' ')}>
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
