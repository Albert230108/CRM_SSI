import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type ModalProps = {
  open: boolean
  onClose: () => void
  children: ReactNode
  /** Extra classes for the panel (e.g. sizing like `max-w-md`). */
  className?: string
  /** Set false to keep the modal open on backdrop click / Escape (e.g. while saving). */
  dismissable?: boolean
  labelledBy?: string
  ariaLabel?: string
}

/**
 * Shared modal shell: portal + animated backdrop (fade) + animated panel (scale-in),
 * Escape-to-close, click-outside-to-close, body scroll lock, and initial focus.
 *
 * The backdrop click uses a mousedown-target guard so a drag that starts inside the
 * panel and releases over the backdrop does not close the modal (matching the existing
 * hand-rolled pattern in ThreadView). Entrance motion is CSS-driven, so it is disabled
 * automatically under prefers-reduced-motion via the global guard in index.css.
 */
export default function Modal({
  open,
  onClose,
  children,
  className = 'w-full max-w-md',
  dismissable = true,
  labelledBy,
  ariaLabel,
}: ModalProps) {
  const backdropMouseDownRef = useRef(false)
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && dismissable) {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)

    // Move focus into the dialog for keyboard users.
    panelRef.current?.focus()

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open, dismissable, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4 bg-gray-900/40 backdrop-blur-sm animate-backdrop-in"
      onMouseDown={(event) => {
        backdropMouseDownRef.current = event.target === event.currentTarget
      }}
      onClick={(event) => {
        if (!dismissable) return
        if (event.target !== event.currentTarget) return
        if (!backdropMouseDownRef.current) return
        backdropMouseDownRef.current = false
        onClose()
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-label={ariaLabel}
        tabIndex={-1}
        className={`relative max-h-[90vh] overflow-hidden outline-none animate-scale-in ${className}`}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  )
}
