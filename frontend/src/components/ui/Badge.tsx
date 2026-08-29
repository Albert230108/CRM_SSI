import type { HTMLAttributes, ReactNode } from 'react'

export type BadgeTone = 'brand' | 'gray' | 'emerald' | 'amber' | 'rose' | 'sky'

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: BadgeTone
  children?: ReactNode
}

const TONES: Record<BadgeTone, string> = {
  brand: 'bg-brand-100 text-brand-700',
  gray: 'bg-gray-100 text-gray-700',
  emerald: 'bg-emerald-100 text-emerald-800',
  amber: 'bg-amber-100 text-amber-800',
  rose: 'bg-rose-100 text-rose-700',
  sky: 'bg-sky-100 text-sky-700',
}

/**
 * Shared status/label pill. Converges the repeated
 * `rounded-full px-2 py-1 text-xs font-semibold` label chips onto one component.
 */
export default function Badge({ tone = 'gray', className = '', children, ...rest }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${TONES[tone]} ${className}`}
      {...rest}
    >
      {children}
    </span>
  )
}
