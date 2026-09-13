// Tri-state colored charges-vs-payments balance indicator, shared by the editor and New Quotation
// pages. Deposit-refund rows must already be excluded from paymentsTotal by the caller (as both
// pages do), matching the desktop's calculate_and_display_total_payments.

interface BalanceBannerProps {
  chargesTotal: number
  paymentsTotal: number
}

export default function BalanceBanner({ chargesTotal, paymentsTotal }: BalanceBannerProps) {
  const diff = Math.round((chargesTotal - paymentsTotal) * 100) / 100
  const state = Math.abs(diff) <= 0.01 ? 'balanced' : paymentsTotal < chargesTotal ? 'under' : 'over'
  const amount = Math.abs(diff)

  return (
    <div
      className={`rounded-xl border p-3 text-sm font-medium ${
        state === 'balanced'
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
          : state === 'under'
            ? 'border-rose-200 bg-rose-50 text-rose-700'
            : 'border-amber-200 bg-amber-50 text-amber-700'
      }`}
    >
      {state === 'balanced'
        ? '✓ Charges and payments are balanced'
        : state === 'under'
          ? `⚠️ Payments are €${amount.toFixed(2)} less than charges`
          : `⚠️ Payments are €${amount.toFixed(2)} more than charges`}
    </div>
  )
}
