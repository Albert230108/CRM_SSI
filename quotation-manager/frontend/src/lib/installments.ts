export const MIN_INSTALLMENTS = 1
export const MAX_INSTALLMENTS = 24

// The desktop's installment default: nights // 30 + 1, clamped to [1, 24].
export function autoInstallments(nights: number | null, fallback = MIN_INSTALLMENTS): number {
  if (nights === null) return fallback
  return Math.max(MIN_INSTALLMENTS, Math.min(Math.floor(nights / 30) + 1, MAX_INSTALLMENTS))
}
