import { forwardRef, useId, type ReactNode, type TextareaHTMLAttributes } from 'react'

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: ReactNode
  error?: string
  wrapperClassName?: string
}

const FIELD =
  'w-full rounded-lg border bg-white px-3 py-2 text-sm text-gray-900 outline-none transition ' +
  'placeholder:text-gray-400 focus:ring-2 focus:ring-brand-200 disabled:cursor-not-allowed disabled:bg-gray-50'

/**
 * Shared multi-line field primitive matching Input's styling.
 */
const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, error, className = '', wrapperClassName = '', id, ...rest },
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
      <textarea
        ref={ref}
        id={fieldId}
        aria-invalid={error ? true : undefined}
        className={`${FIELD} ${borderClass} ${className}`}
        {...rest}
      />
      {error ? <p className="mt-1 text-xs text-rose-500">{error}</p> : null}
    </div>
  )
})

export default Textarea
