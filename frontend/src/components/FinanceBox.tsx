import { useEffect, useMemo, useState } from 'react'
import { useAuthStore } from '../store/authStore'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type FinanceItem = {
  id: number
  amount: string
  currency: string
  description: string | null
  created_at: string
}

type FinanceResponse = {
  tenant: {
    id: number
    booking_id: string
    name: string
  }
  items: FinanceItem[]
}

type FinanceBoxProps = {
  tenantId?: number
}

export default function FinanceBox({ tenantId }: FinanceBoxProps) {
  const token = useAuthStore((state) => state.token)
  const [items, setItems] = useState<FinanceItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!tenantId) {
      setItems([])
      setError('')
      setLoading(false)
      return
    }

    const controller = new AbortController()
    const loadFinance = async () => {
      try {
        setLoading(true)
        setError('')
        const response = await fetch(`${API_BASE_URL}/api/tenants/${tenantId}/finance`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Failed to load finance data')
        const data: FinanceResponse = await response.json()
        setItems(data.items)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Failed to load finance data')
      } finally {
        setLoading(false)
      }
    }

    loadFinance()
    return () => controller.abort()
  }, [tenantId, token])

  const totals = useMemo(() => {
    return items.reduce(
      (acc, item) => {
        const amount = Number(item.amount)
        if (Number.isFinite(amount)) acc.total += amount
        return acc
      },
      { total: 0 },
    )
  }, [items])

  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs uppercase tracking-[0.35em] text-cyan-400">Finance</p>
        <h2 className="mt-1 text-xl font-semibold text-white">Payments and charges</h2>
        <p className="mt-1 text-sm text-slate-400">{tenantId ? `Tenant #${tenantId}` : 'Select a tenant to view finance data'}</p>
      </div>

      {loading ? <p className="text-sm text-slate-400">Loading finance...</p> : null}
      {error ? <p className="text-sm text-rose-400">{error}</p> : null}

      {!tenantId ? null : (
        <div className="rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-slate-400">Entries</p>
            <p className="text-sm font-semibold text-cyan-300">Total {totals.total.toFixed(2)}</p>
          </div>

          <div className="mt-4 overflow-hidden rounded-xl border border-slate-800">
            <table className="w-full border-collapse text-left text-sm">
              <thead className="bg-slate-900/90 text-xs uppercase tracking-[0.2em] text-slate-500">
                <tr>
                  <th className="px-3 py-3">Date</th>
                  <th className="px-3 py-3">Description</th>
                  <th className="px-3 py-3">Amount</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && !loading ? (
                  <tr>
                    <td className="px-3 py-4 text-slate-500" colSpan={3}>No finance entries found.</td>
                  </tr>
                ) : null}
                {items.map((item) => (
                  <tr key={item.id} className="border-t border-slate-800">
                    <td className="px-3 py-3 text-slate-400">{new Date(item.created_at).toLocaleDateString()}</td>
                    <td className="px-3 py-3 text-slate-200">{item.description || 'Finance item'}</td>
                    <td className="px-3 py-3 font-medium text-white">{item.currency} {Number(item.amount).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
