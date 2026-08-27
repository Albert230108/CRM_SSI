import { useEffect, useRef, useState } from 'react'

export type InsertTokenItem = {
  value: string
  label: string
  secondaryLabel?: string
  title?: string
}

export type InsertTokenGroup = {
  label: string
  tokens: InsertTokenItem[]
  emptyMessage?: string
}

export function insertAtCaret(
  element: HTMLTextAreaElement | null,
  value: string,
  token: string,
  onChange: (next: string) => void,
) {
  if (!element) {
    onChange(value + token)
    return
  }
  const start = element.selectionStart ?? value.length
  const end = element.selectionEnd ?? start
  onChange(value.slice(0, start) + token + value.slice(end))
  requestAnimationFrame(() => {
    element.focus()
    const caret = start + token.length
    element.setSelectionRange(caret, caret)
  })
}

type InsertTokenMenuProps = {
  groups: InsertTokenGroup[]
  onInsert: (token: string) => void
}

export function InsertTokenMenu({ groups, onInsert }: InsertTokenMenuProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const handleClickAway = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickAway)
    return () => document.removeEventListener('mousedown', handleClickAway)
  }, [open])

  const visibleGroups = groups.filter((group) => group.tokens.length > 0 || group.emptyMessage)

  const choose = (token: string) => {
    onInsert(token)
    setOpen(false)
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="rounded-lg border border-gray-300 px-2.5 py-1 text-xs font-semibold text-gray-700 hover:bg-gray-100"
      >
        + Insert
      </button>
      {open ? (
        <div className="absolute right-0 z-10 mt-1 max-h-72 w-72 overflow-y-auto rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
          {visibleGroups.length === 0 ? (
            <p className="px-2 py-2 text-xs text-gray-400">No tokens available.</p>
          ) : null}
          {visibleGroups.map((group) => (
            <div key={group.label} className="py-1 first:pt-0 last:pb-0">
              <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-400">{group.label}</p>
              {group.tokens.length === 0 ? (
                <p className="px-2 py-1 text-xs text-gray-400">{group.emptyMessage ?? 'No tokens available.'}</p>
              ) : (
                group.tokens.map((token) => (
                  <button
                    key={token.value}
                    type="button"
                    onClick={() => choose(token.value)}
                    title={token.title}
                    className="block w-full rounded px-2 py-1 text-left text-xs text-gray-700 hover:bg-gray-100"
                  >
                    <span className="font-mono">{token.label}</span>
                    {token.secondaryLabel ? <span className="ml-2 font-mono text-gray-400">{token.secondaryLabel}</span> : null}
                  </button>
                ))
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
