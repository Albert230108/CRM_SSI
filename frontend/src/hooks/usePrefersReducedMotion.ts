import { useEffect, useState } from 'react'

const PREFERS_REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

/**
 * Tracks the user's OS-level "reduce motion" accessibility preference so animated
 * components can opt out of motion. Reactive to the setting changing at runtime.
 */
export function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    window.matchMedia(PREFERS_REDUCED_MOTION_QUERY).matches,
  )

  useEffect(() => {
    const mediaQuery = window.matchMedia(PREFERS_REDUCED_MOTION_QUERY)
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches)

    updatePreference()
    mediaQuery.addEventListener('change', updatePreference)
    return () => mediaQuery.removeEventListener('change', updatePreference)
  }, [])

  return prefersReducedMotion
}
