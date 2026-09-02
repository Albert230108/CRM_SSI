import type { EditableInvoiceItem } from '../lib/types'

const MIN_INSTALLMENTS = 1
const MAX_INSTALLMENTS = 24

interface PaymentsTableProps {
  items: EditableInvoiceItem[]
  onChange: (localId: string, patch: Partial<EditableInvoiceItem>) => void
  onRemove: (localId: string) => void
  onAdd: () => void
  installments: number
  onInstallmentsChange: (n: number) => void
  onAddPaymentPlan: () => void
  buildingPlan: boolean
}

export default function PaymentsTable({
  items,
  onChange,
  onRemove,
  onAdd,
  installments,
  onInstallmentsChange,
  onAddPaymentPlan,
  buildingPlan,
}: PaymentsTableProps) {
  // The deposit-refund row (negative) is excluded from the "total paid" figure,
  // matching the desktop app's calculate_and_display_total_payments.
  const totalPaid = items.reduce((sum, item) => {
    if (item.description.toLowerCase().includes('refund of deposit')) return sum
    return sum + item.qty * item.amount
  }, 0)

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-gray-500">Payments</h2>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-gray-500">
            Installments
            <select
              value={installments}
              onChange={(e) => onInstallmentsChange(Number(e.target.value))}
              className="rounded border border-gray-200 px-1 py-1 text-xs"
            >
              {Array.from({ length: MAX_INSTALLMENTS - MIN_INSTALLMENTS + 1 }, (_, i) => MIN_INSTALLMENTS + i).map(
                (n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ),
              )}
            </select>
          </label>
          <button
            type="button"
            onClick={onAddPaymentPlan}
            disabled={buildingPlan}
            className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {buildingPlan ? 'Building...' : 'Add payment plan'}
          </button>
          <button
            type="button"
            onClick={onAdd}
            className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            + Add payment
          </button>
        </div>
      </div>
      <p className="mt-1 text-xs text-gray-400">
        Generated locally. Nothing changes on the booking until you push to Beds24.
      </p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
              <th className="pb-2">Description</th>
              <th className="w-16 pb-2">Qty</th>
              <th className="w-24 pb-2">Amount</th>
              <th className="w-16 pb-2">VAT %</th>
              <th className="w-24 pb-2">Status</th>
              <th className="w-10 pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.localId} className="border-t border-gray-100">
                <td className="py-1 pr-2">
                  <input
                    type="text"
                    value={item.description}
                    onChange={(e) => onChange(item.localId, { description: e.target.value })}
                    className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    value={item.qty}
                    onChange={(e) => onChange(item.localId, { qty: Number(e.target.value) })}
                    className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="0.01"
                    value={item.amount}
                    onChange={(e) => onChange(item.localId, { amount: Number(e.target.value) })}
                    className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    value={item.vat_rate}
                    onChange={(e) => onChange(item.localId, { vat_rate: Number(e.target.value) })}
                    className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="text"
                    value={item.status ?? ''}
                    onChange={(e) => onChange(item.localId, { status: e.target.value })}
                    className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1 text-right">
                  <button
                    type="button"
                    onClick={() => onRemove(item.localId)}
                    className="text-xs text-rose-500 hover:text-rose-700"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-3 text-center text-xs text-gray-400">
                  No payments yet — pick installments and "Add payment plan", or add a row.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-2 flex justify-end text-sm font-semibold text-gray-900">
        Total paid: €{totalPaid.toFixed(2)}
      </div>
    </div>
  )
}
