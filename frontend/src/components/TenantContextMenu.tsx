import { useEffect, useRef, useState } from 'react'

type PlannerMode = 'off' | 'manual' | 'auto-draft' | 'auto-send'

const PLANNER_MODE_OPTIONS: { value: PlannerMode; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'manual', label: 'Manual' },
  { value: 'auto-draft', label: 'Auto-draft' },
  { value: 'auto-send', label: 'Auto-send' },
]

type TenantContextMenuProps = {
  x: number
  y: number
  onEditAiTemplates: () => void
  onSetPlannerMode: (mode: PlannerMode) => void
  currentPlannerMode: PlannerMode | null
  plannerModeLoading: boolean
  onPlannerMenuOpen: () => void
  onClose: () => void
}

export default function TenantContextMenu({
  x,
  y,
  onEditAiTemplates,
  onSetPlannerMode,
  currentPlannerMode,
  plannerModeLoading,
  onPlannerMenuOpen,
  onClose,
}: TenantContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [plannerMenuOpen, setPlannerMenuOpen] = useState(false)

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) onClose()
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  return (
    <div
      ref={menuRef}
      style={{ position: 'fixed', top: y, left: x }}
      className="z-50 min-w-[10rem] rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
    >
      <button
        type="button"
        onClick={() => {
          onEditAiTemplates()
          onClose()
        }}
        className="block w-full px-3 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-50"
      >
        Edit AI templates
      </button>
      <div className="my-1 border-t border-gray-100" />
      <button
        type="button"
        onClick={() =>
          setPlannerMenuOpen((current) => {
            const next = !current
            if (next) onPlannerMenuOpen()
            return next
          })
        }
        className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-50"
      >
        Planner mode
        <span className="text-xs text-gray-400">{plannerMenuOpen ? '▾' : '▸'}</span>
      </button>
      {plannerMenuOpen ? (
        plannerModeLoading && currentPlannerMode === null ? (
          <p className="py-1.5 pl-6 pr-3 text-xs text-gray-400">Loading...</p>
        ) : (
          PLANNER_MODE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => {
                onSetPlannerMode(option.value)
                onClose()
              }}
              className="flex w-full items-center justify-between py-1.5 pl-6 pr-3 text-left text-sm text-gray-700 hover:bg-gray-50"
            >
              {option.label}
              {currentPlannerMode === option.value ? <span className="text-brand-600">&#10003;</span> : null}
            </button>
          ))
        )
      ) : null}
    </div>
  )
}
