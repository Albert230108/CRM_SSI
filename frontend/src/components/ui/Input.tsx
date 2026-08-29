import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  label?: ReactNode
  error?: string
  /** Wrapper classes (e.g. layout/width). Field classes go on the input itself. */
  wrapperClassName?: string
}

const FIELD =
  'w-full rounded-lg border bg-white px-3 py-2 text-sm text-gray-900 outline-none transition ' +
  'placeholder:text-gray-400 focus:ring-2 focus:ring-brand-200 disabled:cursor-not-allowed disabled:bg-gray-50'

/**
 * Shared text-field primitive: converges the app's hand-rolled inputs onto one
 * border/radius/focus treatment (brand focus ring). Renders an optional label and
 * error message with wired-up ids for accessibility.
 */
const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, className = '', wrapperClassName = '', id, ...rest },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const borderClass = error ? 'border-rose-300 focus:border-rose-400' : 'border-gray-300 focus:border-brand-500'

  return (
    <div className={wrapperClassName}>
      {label ? (
        <label htmlFor={inputId} className="mb-1.5 block text-sm text-gray-700">
          {label}
        </label>
      ) : null}
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        className={`${FIELD} ${borderClass} ${className}`}
        {...rest}
      />
      {error ? <p className="mt-1 text-xs text-rose-500">{error}</p> : null}
    </div>
  )
})

export default Input
