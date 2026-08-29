import { useEffect, useMemo, useRef, useState } from 'react'
import {
  type ComposerBodyFormat,
  hasComposerContent,
  htmlToPlainText,
  plainTextToHtml,
  sanitizeComposerHtml,
  whatsappHtmlToMarkup,
  whatsappMarkupToHtml,
} from '../lib/messageFormatting'

type ComposerValue = {
  body: string
  bodyHtml: string | null
  bodyFormat: ComposerBodyFormat
}

type RichMessageComposerProps = {
  channel: 'email' | 'whatsapp'
  value: ComposerValue
  placeholder: string
  disabled?: boolean
  onChange: (next: ComposerValue) => void
}

type ToolbarAction = {
  label: string
  ariaLabel: string
  command: string
  value?: string
}

const EMAIL_ACTIONS: ToolbarAction[] = [
  { label: 'B', ariaLabel: 'Bold', command: 'bold' },
  { label: 'I', ariaLabel: 'Italic', command: 'italic' },
  { label: 'U', ariaLabel: 'Underline', command: 'underline' },
  { label: '☷', ariaLabel: 'Bulleted list', command: 'insertUnorderedList' },
]

const WHATSAPP_ACTIONS: ToolbarAction[] = [
  { label: 'B', ariaLabel: 'Bold', command: 'bold' },
  { label: 'I', ariaLabel: 'Italic', command: 'italic' },
  { label: 'S', ariaLabel: 'Strikethrough', command: 'strikeThrough' },
]

export default function RichMessageComposer({ channel, value, placeholder, disabled = false, onChange }: RichMessageComposerProps) {
  const editorRef = useRef<HTMLDivElement | null>(null)
  const [activeCommands, setActiveCommands] = useState<Set<string>>(new Set())
  const desiredHtml = useMemo(() => {
    if (value.bodyFormat === 'email_html' && value.bodyHtml) return sanitizeComposerHtml(value.bodyHtml)
    if (value.bodyFormat === 'whatsapp_rich') return sanitizeComposerHtml(value.bodyHtml || whatsappMarkupToHtml(value.body))
    return plainTextToHtml(value.body)
  }, [value.body, value.bodyHtml, value.bodyFormat])
  const toolbarActions = channel === 'email' ? EMAIL_ACTIONS : WHATSAPP_ACTIONS

  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    const currentHtml = sanitizeComposerHtml(editor.innerHTML)
    if (currentHtml === desiredHtml) return
    editor.innerHTML = desiredHtml
  }, [desiredHtml])

  const readEditorValue = (): ComposerValue | null => {
    const editor = editorRef.current
    if (!editor) return null
    const sanitizedHtml = sanitizeComposerHtml(editor.innerHTML)
    if (channel === 'email') {
      const body = htmlToPlainText(sanitizedHtml)
      return {
        body,
        bodyHtml: sanitizedHtml || null,
        bodyFormat: hasComposerContent(body, sanitizedHtml) ? 'email_html' : 'plain',
      }
    }
    const body = whatsappHtmlToMarkup(sanitizedHtml)
    return {
      body,
      bodyHtml: sanitizedHtml || null,
      bodyFormat: hasComposerContent(body, sanitizedHtml) ? 'whatsapp_rich' : 'plain',
    }
  }

  const emitChange = () => {
    const nextValue = readEditorValue()
    if (!nextValue) return
    onChange(nextValue)
  }

  const normalizeEditorMarkup = () => {
    const editor = editorRef.current
    if (!editor) return
    const sanitizedHtml = sanitizeComposerHtml(editor.innerHTML)
    if (editor.innerHTML !== sanitizedHtml) editor.innerHTML = sanitizedHtml
  }

  const runCommand = (action: ToolbarAction) => {
    if (disabled || !editorRef.current || typeof document.execCommand !== 'function') return
    editorRef.current.focus()
    document.execCommand(action.command, false, action.value)
    setActiveCommands((current) => {
      const next = new Set(current)
      if (document.queryCommandState(action.command)) next.add(action.command)
      else next.delete(action.command)
      return next
    })
    emitChange()
  }

  const isEmpty = !hasComposerContent(value.body, value.bodyHtml)

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {toolbarActions.map((action) => (
          <button
            key={`${channel}-${action.command}-${action.label}`}
            type="button"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => runCommand(action)}
            disabled={disabled}
            aria-label={action.ariaLabel}
            aria-pressed={activeCommands.has(action.command)}
            className={`rounded-md border px-2 py-1 text-[11px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
              activeCommands.has(action.command)
                ? 'border-brand-500 bg-brand-50 text-brand-700'
                : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-50'
            }`}
          >
            {action.label}
          </button>
        ))}
      </div>
      <div className="relative">
        {isEmpty ? <span className="pointer-events-none absolute left-3 top-2 text-sm text-gray-400">{placeholder}</span> : null}
        <div
          ref={editorRef}
          role="textbox"
          aria-label={placeholder}
          aria-multiline="true"
          contentEditable={!disabled}
          suppressContentEditableWarning
          spellCheck
          onInput={emitChange}
          onBlur={() => {
            normalizeEditorMarkup()
            emitChange()
          }}
          className="min-h-[5.5rem] w-full overflow-y-auto rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 outline-none focus:border-brand-500 disabled:cursor-not-allowed disabled:bg-gray-50 [&_ul]:list-disc [&_ol]:list-decimal [&_ul]:pl-5 [&_ol]:pl-5"
        />
      </div>
    </div>
  )
}
