import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { withAiSettingsReturn } from '../lib/aiSettingsNavigation'
import { aiSettingsLinks } from '../lib/aiSettingsLinks'

type AiSettingsDropdownProps = {
  children: ReactNode
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, to: string) => void
}

const CLOSE_DELAY_MS = 150

export default function AiSettingsDropdown({ children, onNavigate }: AiSettingsDropdownProps) {
  const [open, setOpen] = useState(false)
  const closeTimerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current)
      }
    }
  }, [])

  const cancelClose = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }

  const scheduleClose = () => {
    cancelClose()
    closeTimerRef.current = window.setTimeout(() => {
      setOpen(false)
      closeTimerRef.current = null
    }, CLOSE_DELAY_MS)
  }

  return (
    <div
      className="relative inline-flex items-center"
      onMouseEnter={() => {
        cancelClose()
        setOpen(true)
      }}
      onMouseLeave={scheduleClose}
    >
      {children}
      {open ? (
        <div
          className="absolute left-0 top-full z-10 mt-1 w-80 rounded-lg border border-gray-200 bg-white p-1.5 shadow-lg"
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
        >
          {aiSettingsLinks.map((item) => (
            <Link
              key={item.to}
              to={withAiSettingsReturn(item.to)}
              onClick={(event) => onNavigate(event, withAiSettingsReturn(item.to))}
              className="group flex items-start justify-between gap-3 rounded-md px-3 py-2 text-left transition hover:bg-gray-50"
            >
              <div>
                <p className="text-sm font-semibold text-gray-900 group-hover:text-indigo-700">{item.label}</p>
                <p className="mt-0.5 text-xs leading-5 text-gray-500">{item.description}</p>
              </div>
              <span className="mt-0.5 rounded-full bg-indigo-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-indigo-700">
                Open
              </span>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  )
}
