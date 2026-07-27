import { useEffect, useRef } from 'react'

type TenantContextMenuProps = {
  x: number
  y: number
  onEditAiTemplates: () => void
  onClose: () => void
}

export default function TenantContextMenu({ x, y, onEditAiTemplates, onClose }: TenantContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

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
    </div>
  )
}
