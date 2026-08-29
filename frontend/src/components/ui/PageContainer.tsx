import type { ReactNode } from 'react'

type PageContainerProps = {
  children: ReactNode
  /** Extra classes for the root element. */
  className?: string
  /** Max-width utility for the centered content (ignored when `fullBleed`). */
  maxWidthClassName?: string
  /** Skip the centered max-width + padding wrapper (for full-bleed pages like Dashboard). */
  fullBleed?: boolean
}

/**
 * Standard page root. Provides a consistent centered max-width + padding and, more
 * importantly, a mount entrance animation so navigating to a route gently animates its
 * content in. React Router mounts a fresh page component per navigation, so the CSS
 * animation plays once on arrival; reduced-motion is honored via the global guard in
 * index.css. Full-bleed pages pass `fullBleed` to keep their own layout and just take
 * the entrance.
 */
export default function PageContainer({
  children,
  className = '',
  maxWidthClassName = 'max-w-6xl',
  fullBleed = false,
}: PageContainerProps) {
  if (fullBleed) {
    return <div className={`animate-slide-up ${className}`}>{children}</div>
  }
  return (
    <div className={`animate-slide-up mx-auto ${maxWidthClassName} px-6 py-4 ${className}`}>{children}</div>
  )
}
