import { useCallback, useRef, useState } from 'react'

export type ToastState = { id: number; kind: 'success' | 'error'; message: string } | null

const AUTO_DISMISS_MS = 4000

export function useToast() {
  const [toast, setToast] = useState<ToastState>(null)
  const timeoutRef = useRef<number | null>(null)

  const dismiss = useCallback(() => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
    setToast(null)
  }, [])

  const show = useCallback((kind: 'success' | 'error', message: string) => {
    if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current)
    const id = Date.now()
    setToast({ id, kind, message })
    timeoutRef.current = window.setTimeout(() => {
      setToast((current) => (current?.id === id ? null : current))
    }, AUTO_DISMISS_MS)
  }, [])

  const showSuccess = useCallback((message: string) => show('success', message), [show])
  const showError = useCallback((message: string) => show('error', message), [show])

  return { toast, showSuccess, showError, dismiss }
}
