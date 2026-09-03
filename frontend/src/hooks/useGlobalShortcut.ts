import { useEffect } from 'react'

/**
 * Binds a global Cmd/Ctrl+<key> shortcut. Fires `handler` and prevents the browser default
 * (e.g. Chrome's built-in Ctrl+K search) while the app is mounted.
 */
export function useGlobalShortcut(key: string, handler: () => void, enabled = true) {
  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === key.toLowerCase()) {
        event.preventDefault()
        handler()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [key, handler, enabled])
}

export default useGlobalShortcut
