import { useEffect, useMemo, useRef } from 'react'
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
  command: string
  value?: string
}

const EMAIL_ACTIONS: ToolbarAction[] = [
  { label: 'B', command: 'bold' },
  { label: 'I', command: 'italic' },
  { label: 'U', command: 'underline' },
  { label: 'List', command: 'insertUnorderedList' },
]

const WHATSAPP_ACTIONS: ToolbarAction[] = [
  { label: 'B', command: 'bold' },
  { label: 'I', command: 'italic' },
  { label: 'S', command: 'strikeThrough' },
]

export default function RichMessageComposer({ channel, value, placeholder, disabled = false, onChange }: RichMessageComposerProps) {
  const editorRef = useRef<HTMLDivElement | null>(null)
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

  const emitChange = () => {
    const editor = editorRef.current
    if (!editor) return
    const sanitizedHtml = sanitizeComposerHtml(editor.innerHTML)
    if (editor.innerHTML !== sanitizedHtml) editor.innerHTML = sanitizedHtml
    if (channel === 'email') {
      const body = htmlToPlainText(sanitizedHtml)
      onChange({
        body,
        bodyHtml: sanitizedHtml || null,
        bodyFormat: hasComposerContent(body, sanitizedHtml) ? 'email_html' : 'plain',
      })
      return
    }
    const body = whatsappHtmlToMarkup(sanitizedHtml)
    onChange({
      body,
      bodyHtml: sanitizedHtml || null,
      bodyFormat: hasComposerContent(body, sanitizedHtml) ? 'whatsapp_rich' : 'plain',
    })
  }

  const runCommand = (action: ToolbarAction) => {
    if (disabled || !editorRef.current || typeof document.execCommand !== 'function') return
    editorRef.current.focus()
    document.execCommand(action.command, false, action.value)
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
            className="rounded-md border border-gray-300 bg-white px-2 py-1 text-[11px] font-semibold text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
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
          onBlur={emitChange}
          className="min-h-[5.5rem] w-full overflow-y-auto rounded-lg border border-gray-300 bg-white px-2.5 py-2 text-sm text-gray-900 outline-none focus:border-cyan-500 disabled:cursor-not-allowed disabled:bg-gray-50"
        />
      </div>
    </div>
  )
}
