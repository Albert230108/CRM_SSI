import { forwardRef, useId, type ReactNode, type SelectHTMLAttributes } from 'react'

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label?: ReactNode
  error?: string
  wrapperClassName?: string
  children?: ReactNode
}

const FIELD =
  'w-full rounded-lg border bg-white px-3 py-2 text-sm text-gray-900 outline-none transition ' +
  'focus:ring-2 focus:ring-brand-200 disabled:cursor-not-allowed disabled:bg-gray-50'

/**
 * Shared select primitive matching Input's styling.
 */
const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, error, className = '', wrapperClassName = '', id, children, ...rest },
  ref,
) {
  const generatedId = useId()
  const fieldId = id ?? generatedId
  const borderClass = error ? 'border-rose-300 focus:border-rose-400' : 'border-gray-300 focus:border-brand-500'

  return (
    <div className={wrapperClassName}>
      {label ? (
        <label htmlFor={fieldId} className="mb-1.5 block text-sm text-gray-700">
          {label}
        </label>
      ) : null}
      <select
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        className={`${FIELD} ${borderClass} ${className}`}
        {...rest}
      >
        {children}
      </select>
      {error ? <p className="mt-1 text-xs text-rose-500">{error}</p> : null}
    </div>
  )
})

export default Select
