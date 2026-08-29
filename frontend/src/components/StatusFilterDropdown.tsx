import { useEffect, useRef, useState } from 'react'

type StatusFilterDropdownProps = {
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
}

export default function StatusFilterDropdown({ options, selected, onChange }: StatusFilterDropdownProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const toggleStatus = (status: string) => {
    if (selected.includes(status)) {
      onChange(selected.filter((s) => s !== status))
    } else {
      onChange([...selected, status])
    }
  }

  const label =
    selected.length === 0
      ? 'No Statuses'
      : selected.length === options.length
        ? 'All Statuses'
        : `${selected.length} Status${selected.length > 1 ? 'es' : ''}`

  return (
    <div ref={containerRef} className="relative min-w-0 flex-1">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="w-full truncate rounded-lg border border-gray-200 px-2 py-1 text-left text-xs outline-none focus:border-brand-300 focus:ring-1 focus:ring-brand-200"
      >
        {label}
      </button>
      {open && (
        <div className="absolute z-10 mt-1 w-48 origin-top animate-scale-in rounded-lg border border-gray-200 bg-white p-1.5 shadow-lg">
          <div className="mb-1 flex gap-1 border-b border-gray-100 pb-1">
            <button
              type="button"
              onClick={() => onChange(options)}
              className="flex-1 rounded px-1.5 py-0.5 text-[11px] text-brand-700 hover:bg-brand-50"
            >
              Select all
            </button>
            <button
              type="button"
              onClick={() => onChange([])}
              className="flex-1 rounded px-1.5 py-0.5 text-[11px] text-gray-500 hover:bg-gray-50"
            >
              Clear all
            </button>
          </div>
          <div className="max-h-48 space-y-0.5 overflow-y-auto">
            {options.map((status) => (
              <label
                key={status}
                className="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-xs hover:bg-gray-50"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(status)}
                  onChange={() => toggleStatus(status)}
                  className="h-3.5 w-3.5 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                />
                <span className="truncate">{status}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
