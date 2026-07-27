import type { EditableInvoiceItem } from '../lib/types'

interface PaymentsTableProps {
  items: EditableInvoiceItem[]
}

export default function PaymentsTable({ items }: PaymentsTableProps) {
  const totalPaid = items.reduce((sum, item) => sum + item.qty * item.amount, 0)

  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold uppercase tracking-[0.15em] text-gray-500">Payments</h2>
      <p className="mt-1 text-xs text-gray-400">From Beds24 — read-only here, managed via the booking itself.</p>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
              <th className="pb-2">Description</th>
              <th className="w-24 pb-2">Amount</th>
              <th className="w-24 pb-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.localId} className="border-t border-gray-100">
                <td className="py-1 pr-2 text-gray-700">{item.description}</td>
                <td className="py-1 pr-2 text-gray-700">€{(item.qty * item.amount).toFixed(2)}</td>
                <td className="py-1 pr-2 text-gray-500">{item.status ?? 'not paid'}</td>
              </tr>
            ))}
            {items.length === 0 ? (
              <tr>
                <td colSpan={3} className="py-3 text-center text-xs text-gray-400">
                  No payments recorded
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
