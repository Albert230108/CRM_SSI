import { useEffect, useRef, useState, type ReactNode } from 'react'

export type MultiSelectOption<T extends string> = {
  value: T
  label: string
  /** Optional CSS color for a small leading swatch dot (e.g. tag colors). */
  color?: string
}

type MultiSelectProps<T extends string> = {
  /** Field name shown on the trigger, e.g. "Due" or "Tags". */
  label: string
  options: MultiSelectOption<T>[]
  selected: T[]
  onChange: (next: T[]) => void
  /** Single-pick mode: choosing an option replaces the selection and closes. */
  singleSelect?: boolean
  /** Overrides the trigger text (used by single-select filters that always have a value). */
  summary?: (selected: T[]) => string
  /** Extra content rendered at the bottom of the popover (e.g. an Any/All match toggle). */
  footer?: ReactNode
  className?: string
}

/**
 * Compact dropdown filter matching the toolbar pill sizing. Generalized from the
 * click-outside checkbox pattern in StatusFilterDropdown so filters can collapse into
 * a single row instead of stacked button rows.
 */
export default function MultiSelect<T extends string>({
  label,
  options,
  selected,
  onChange,
  singleSelect = false,
  summary,
  footer,
  className = '',
}: MultiSelectProps<T>) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const toggle = (value: T) => {
    if (singleSelect) {
      onChange([value])
      setOpen(false)
      return
    }
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value])
  }

  const triggerText = summary ? summary(selected) : label
  const badgeCount = singleSelect ? 0 : selected.length

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
          badgeCount > 0 ? 'border-brand-300 bg-brand-50 text-brand-700' : 'border-gray-300 text-gray-700 hover:bg-gray-100'
        }`}
      >
        <span>{triggerText}</span>
        {badgeCount > 0 ? (
          <span className="rounded-full bg-brand-600 px-1.5 text-[10px] font-semibold text-white">{badgeCount}</span>
        ) : null}
        <span className="text-[9px] text-gray-400">▾</span>
      </button>
      {open ? (
        <div className="absolute z-20 mt-1 w-52 origin-top animate-scale-in rounded-lg border border-gray-200 bg-white p-1.5 shadow-lg">
          {!singleSelect ? (
            <div className="mb-1 flex gap-1 border-b border-gray-100 pb-1">
              <button
                type="button"
                onClick={() => onChange(options.map((option) => option.value))}
                className="flex-1 rounded px-1.5 py-0.5 text-[11px] text-brand-700 hover:bg-brand-50"
              >
                Select all
              </button>
              <button type="button" onClick={() => onChange([])} className="flex-1 rounded px-1.5 py-0.5 text-[11px] text-gray-500 hover:bg-gray-50">
                Clear all
              </button>
            </div>
          ) : null}
          <div className="max-h-56 space-y-0.5 overflow-y-auto">
            {options.map((option) => {
              const isSelected = selected.includes(option.value)
              return (
                <label key={option.value} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-gray-50">
                  <input
                    type={singleSelect ? 'radio' : 'checkbox'}
                    checked={isSelected}
                    onChange={() => toggle(option.value)}
                    className="h-3.5 w-3.5 border-gray-300 text-brand-600 focus:ring-brand-500"
                  />
                  {option.color ? <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: option.color }} /> : null}
                  <span className="truncate">{option.label}</span>
                </label>
              )
            })}
          </div>
          {footer ? <div className="mt-1 border-t border-gray-100 pt-1">{footer}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
