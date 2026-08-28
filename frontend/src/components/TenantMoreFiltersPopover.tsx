import { useEffect, useRef, useState } from 'react'

type TenantMoreFiltersPopoverProps = {
  selectedResponsible: string | null
  onResponsibleChange: (next: string | null) => void
  uniqueResponsibles: string[]
  selectedDirection: string | null
  onDirectionChange: (next: string | null) => void
}

export default function TenantMoreFiltersPopover({
  selectedResponsible,
  onResponsibleChange,
  uniqueResponsibles,
  selectedDirection,
  onDirectionChange,
}: TenantMoreFiltersPopoverProps) {
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

  const hasActiveFilters = selectedResponsible != null || selectedDirection != null

  return (
    <div ref={containerRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-pressed={open}
        title="More filters"
        className={[
          'relative rounded-lg border px-2 py-1 text-xs font-medium transition',
          hasActiveFilters
            ? 'border-cyan-500 bg-cyan-50 text-cyan-700'
            : 'border-gray-200 text-gray-500 hover:bg-gray-50',
        ].join(' ')}
      >
        More filters
        {hasActiveFilters ? (
          <span
            aria-hidden="true"
            className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-cyan-500"
          />
        ) : null}
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-56 space-y-1.5 rounded-lg border border-gray-200 bg-white p-1.5 shadow-lg">
          <select
            value={selectedResponsible || ''}
            onChange={(e) => onResponsibleChange(e.target.value || null)}
            className="w-full rounded-lg border border-gray-200 px-2 py-1 text-xs outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
          >
            <option value="">All Responsible</option>
            <option value="unassigned">Unassigned</option>
            {uniqueResponsibles.map((responsible) => (
              <option key={responsible} value={responsible}>
                {responsible}
              </option>
            ))}
          </select>

          <select
            value={selectedDirection || ''}
            onChange={(e) => onDirectionChange(e.target.value || null)}
            className="w-full rounded-lg border border-gray-200 px-2 py-1 text-xs outline-none focus:border-cyan-300 focus:ring-1 focus:ring-cyan-200"
          >
            <option value="">Any</option>
            <option value="inbound">Inbound</option>
            <option value="outbound">Outbound</option>
          </select>

          {hasActiveFilters ? (
            <button
              type="button"
              onClick={() => {
                onResponsibleChange(null)
                onDirectionChange(null)
              }}
              className="w-full rounded px-1.5 py-1 text-[11px] text-gray-500 hover:bg-gray-50"
            >
              Clear filters
            </button>
          ) : null}
        </div>
      )}
    </div>
  )
}
