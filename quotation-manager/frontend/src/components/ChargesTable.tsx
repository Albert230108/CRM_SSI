import type { EditableInvoiceItem } from '../lib/types'

interface ChargesTableProps {
  items: EditableInvoiceItem[]
  onChange: (localId: string, patch: Partial<EditableInvoiceItem>) => void
  onRemove: (localId: string) => void
  onAdd: () => void
}

export default function ChargesTable({ items, onChange, onRemove, onAdd }: ChargesTableProps) {
  // Charge amounts on the quotation form are VAT-inclusive (see app.services.vat on the
  // backend) - Settings/the pricing config stay VAT-exclusive, this total is form-only.
  const total = items.reduce((sum, item) => sum + item.qty * item.amount, 0)
  const totalVat = items.reduce((sum, item) => {
    const lineTotal = item.qty * item.amount
    const netLineTotal = item.vat_rate ? lineTotal / (1 + item.vat_rate / 100) : lineTotal
    return sum + (lineTotal - netLineTotal)
  }, 0)

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-gray-500">Charges</h2>
        <button
          type="button"
          onClick={onAdd}
          className="rounded-lg border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
        >
          + Add charge
        </button>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
              <th className="pb-2">Charge</th>
              <th className="w-24 pb-2">Status</th>
              <th className="w-16 pb-2">Qty</th>
              <th className="w-24 pb-2">Price (incl. VAT)</th>
              <th className="w-16 pb-2">VAT %</th>
              <th className="w-24 pb-2">Total</th>
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
                    type="text"
                    value={item.status ?? ''}
                    onChange={(e) => onChange(item.localId, { status: e.target.value })}
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
                <td className="py-1 pr-2 text-right tabular-nums text-gray-700">
                  €{(item.qty * item.amount).toFixed(2)}
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
                <td colSpan={7} className="py-3 text-center text-xs text-gray-400">
                  No charges yet
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-2 flex justify-end text-sm font-semibold text-gray-900">
        Total (incl. VAT): €{total.toFixed(2)}
        <span className="ml-2 font-normal text-gray-400">(of which VAT €{totalVat.toFixed(2)})</span>
      </div>
    </div>
  )
}
