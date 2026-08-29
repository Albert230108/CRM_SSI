import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import InlineSpinner from '../InlineSpinner'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  children?: ReactNode
}

const BASE =
  'inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition ' +
  'active:scale-[.98] disabled:cursor-not-allowed disabled:opacity-50 ' +
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-1'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700',
  secondary: 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50',
  ghost: 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
  danger: 'bg-rose-600 text-white hover:bg-rose-700',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-4 py-2 text-sm',
}

/**
 * Shared button primitive: converges the app's hand-rolled buttons onto one set of
 * variants, sizes, radius, focus ring, and press feedback. Handles loading state by
 * disabling and showing an InlineSpinner in place of any leading content.
 */
const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading = false, disabled, className = '', children, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    >
      {loading ? <InlineSpinner size="sm" /> : null}
      {children}
    </button>
  )
})

export default Button
