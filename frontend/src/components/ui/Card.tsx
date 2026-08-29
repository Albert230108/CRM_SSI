import type { HTMLAttributes, ReactNode } from 'react'

type CardProps = HTMLAttributes<HTMLDivElement> & {
  children?: ReactNode
}

/**
 * The repeated tile shell used across the Dashboard columns
 * (`rounded-2xl border border-gray-200 bg-white shadow-sm`). Extracted so radius,
 * border, and elevation stay consistent in one place.
 */
export default function Card({ className = '', children, ...rest }: CardProps) {
  return (
    <div className={`rounded-2xl border border-gray-200 bg-white shadow-sm ${className}`} {...rest}>
      {children}
    </div>
  )
}
