// Captures what a staff member currently has open so the floating assistant can ground its
// answer in it, without needing a screenshot/vision model - just the route, the page title, and
// the visible text of the main content area. See backend/app/services/ai_assistant_service.py
// for how this is folded into the prompt.

const MAX_VISIBLE_TEXT_LENGTH = 4000

// The scroll container that wraps every routed page - see the layout div in App.tsx. The widget
// itself is portaled to document.body, so a plain global selector still finds it fine.
const MAIN_CONTENT_SELECTOR = '.min-h-0.flex-1.overflow-auto'

export type ScreenContext = {
  pathname: string
  tenantId: number | null
  title: string
  visibleText: string
}

export function getScreenContext(pathname: string): ScreenContext {
  const tenantMatch = pathname.match(/\/dashboard\/tenant\/(\d+)/)
  const tenantId = tenantMatch ? Number(tenantMatch[1]) : null

  let visibleText = ''
  try {
    const container = document.querySelector(MAIN_CONTENT_SELECTOR)
    visibleText = (container instanceof HTMLElement ? container.innerText : '').trim().slice(0, MAX_VISIBLE_TEXT_LENGTH)
  } catch {
    // DOM access can fail in exotic embedding contexts; the assistant still works from the
    // route/title alone.
    visibleText = ''
  }

  return {
    pathname,
    tenantId,
    title: document.title,
    visibleText,
  }
}
