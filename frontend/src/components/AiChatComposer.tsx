import type { ReactNode } from 'react'

type AiChatComposerProps = {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  placeholder: string
  disabled?: boolean
  busy?: boolean
  multiline?: boolean
  secondaryAction?: ReactNode
  className?: string
}

export default function AiChatComposer({
  value,
  onChange,
  onSubmit,
  placeholder,
  disabled = false,
  busy = false,
  multiline = false,
  secondaryAction,
  className = '',
}: AiChatComposerProps) {
  return (
    <form
      className={`flex items-center gap-2 rounded-2xl border border-brand-100 bg-white p-2 shadow-sm ${className}`}
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <div className="min-w-0 flex-1 rounded-xl border border-brand-100 bg-brand-50/60 px-3 py-2 transition focus-within:border-brand-300 focus-within:bg-white">
        {multiline ? (
          <textarea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            disabled={disabled}
            rows={3}
            className="min-h-20 w-full resize-none border-0 bg-transparent p-0 text-sm text-gray-900 outline-none placeholder:text-gray-400 disabled:cursor-not-allowed"
          />
        ) : (
          <input
            type="text"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder={placeholder}
            disabled={disabled}
            className="w-full border-0 bg-transparent p-0 text-sm text-gray-900 outline-none placeholder:text-gray-400 disabled:cursor-not-allowed"
          />
        )}
      </div>
      {secondaryAction}
      <button
        type="submit"
        disabled={!value.trim() || disabled}
        className="shrink-0 rounded-full border border-brand-200 bg-brand-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? 'Asking...' : 'Ask'}
      </button>
    </form>
  )
}
