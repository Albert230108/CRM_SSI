import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiGet, apiPut } from '../lib/apiClient'

type TabKey = 'admin-costs' | 'base-prices' | 'prices' | 'discount-rules'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'admin-costs', label: 'Admin costs' },
  { key: 'base-prices', label: 'Base prices' },
  { key: 'prices', label: 'Price tiers' },
  { key: 'discount-rules', label: 'Discounts (JSON)' },
]

type AnyRecord = Record<string, any>

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

const inputClass = 'w-full rounded border border-gray-200 px-2 py-1 text-sm'

export default function SettingsPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabKey>('admin-costs')
  const [data, setData] = useState<AnyRecord | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    setNotice(null)
    setData(null)
    apiGet<AnyRecord>(`/api/config/${tab}`)
      .then(setData)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : 'Failed to load config'))
      .finally(() => setLoading(false))
  }, [tab])

  const save = async (payload: AnyRecord) => {
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const saved = await apiPut<AnyRecord>(`/api/config/${tab}`, payload)
      setData(saved)
      setNotice('Saved. A backup of the previous version was written alongside it.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save config')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Quotation settings</h1>
        <button type="button" onClick={() => navigate('/')} className="text-sm text-gray-500 hover:text-gray-700">
          ← Back
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
              tab === t.key ? 'bg-cyan-600 text-white' : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error ? <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</p> : null}

      {loading || !data ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : tab === 'admin-costs' ? (
        <AdminCostsEditor data={data} saving={saving} onSave={save} />
      ) : tab === 'base-prices' ? (
        <BasePricesEditor data={data} saving={saving} onSave={save} />
      ) : tab === 'prices' ? (
        <PriceTiersEditor data={data} saving={saving} onSave={save} />
      ) : (
        <JsonEditor data={data} saving={saving} onSave={save} />
      )}
    </div>
  )
}

function SaveBar({ saving, onSave }: { saving: boolean; onSave: () => void }) {
  return (
    <button
      type="button"
      onClick={onSave}
      disabled={saving}
      className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-700 disabled:opacity-50"
    >
      {saving ? 'Saving…' : 'Save'}
    </button>
  )
}

function AdminCostsEditor({ data, saving, onSave }: { data: AnyRecord; saving: boolean; onSave: (d: AnyRecord) => void }) {
  const [draft, setDraft] = useState<AnyRecord>(() => clone(data))
  useEffect(() => setDraft(clone(data)), [data])
  const properties = Object.keys(draft.properties ?? {})

  const patch = (prop: string, field: string, value: unknown) =>
    setDraft((prev) => {
      const next = clone(prev)
      next.properties[prop][field] = value
      return next
    })

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">Admin fee = (charges − deposit − city tax) × % , clamped between min and max.</p>
      {properties.map((prop) => {
        const p = draft.properties[prop]
        return (
          <div key={prop} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-900">{prop}</h3>
              <label className="flex items-center gap-2 text-xs text-gray-600">
                <input
                  type="checkbox"
                  checked={Boolean(p.admin_costs_enabled)}
                  onChange={(e) => patch(prop, 'admin_costs_enabled', e.target.checked)}
                />
                Enabled
              </label>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
              <label className="text-xs text-gray-500">
                Percentage %
                <input type="number" step="0.1" value={p.admin_percentage} onChange={(e) => patch(prop, 'admin_percentage', Number(e.target.value))} className={inputClass} />
              </label>
              <label className="text-xs text-gray-500">
                Min (€)
                <input type="number" step="0.01" value={p.admin_min} onChange={(e) => patch(prop, 'admin_min', Number(e.target.value))} className={inputClass} />
              </label>
              <label className="text-xs text-gray-500">
                Max (€)
                <input type="number" step="0.01" value={p.admin_max} onChange={(e) => patch(prop, 'admin_max', Number(e.target.value))} className={inputClass} />
              </label>
              <label className="text-xs text-gray-500">
                Description
                <input value={p.description ?? ''} onChange={(e) => patch(prop, 'description', e.target.value)} className={inputClass} />
              </label>
            </div>
          </div>
        )
      })}
      <SaveBar saving={saving} onSave={() => onSave(draft)} />
    </div>
  )
}

function BasePricesEditor({ data, saving, onSave }: { data: AnyRecord; saving: boolean; onSave: (d: AnyRecord) => void }) {
  const [draft, setDraft] = useState<AnyRecord>(() => clone(data))
  useEffect(() => setDraft(clone(data)), [data])
  const properties = Object.keys(draft.properties ?? {})

  const patch = (prop: string, room: string, field: string, value: unknown) =>
    setDraft((prev) => {
      const next = clone(prev)
      next.properties[prop][room][field] = value
      return next
    })

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">Base per-night prices (excl. VAT) used as the foundation for discount calculations.</p>
      {properties.map((prop) => (
        <div key={prop} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-900">{prop}</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                  <th className="pb-2">Room</th>
                  <th className="w-32 pb-2">Base price (€)</th>
                  <th className="pb-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(draft.properties[prop]).map((room) => {
                  const r = draft.properties[prop][room]
                  return (
                    <tr key={room} className="border-t border-gray-100">
                      <td className="py-1 pr-2 text-gray-700">{room}</td>
                      <td className="py-1 pr-2">
                        <input type="number" step="0.01" value={r.base_price ?? 0} onChange={(e) => patch(prop, room, 'base_price', Number(e.target.value))} className={inputClass} />
                      </td>
                      <td className="py-1 pr-2">
                        <input value={r.notes ?? ''} onChange={(e) => patch(prop, room, 'notes', e.target.value)} className={inputClass} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      <SaveBar saving={saving} onSave={() => onSave(draft)} />
    </div>
  )
}

const TIER_KEYS = ['7', '14', '30', '60', '90']

function PriceTiersEditor({ data, saving, onSave }: { data: AnyRecord; saving: boolean; onSave: (d: AnyRecord) => void }) {
  const [draft, setDraft] = useState<AnyRecord>(() => clone(data))
  useEffect(() => setDraft(clone(data)), [data])

  const years = useMemo(() => Object.keys(draft).filter((k) => /^\d{4}$/.test(k)).sort(), [draft])
  const [year, setYear] = useState(years[0] ?? '')
  useEffect(() => {
    if (!years.includes(year)) setYear(years[0] ?? '')
  }, [years, year])

  const properties = year ? Object.keys(draft[year] ?? {}) : []
  const [prop, setProp] = useState(properties[0] ?? '')
  useEffect(() => {
    if (!properties.includes(prop)) setProp(properties[0] ?? '')
  }, [properties, prop])

  if (!year || !prop) return <p className="text-sm text-gray-500">No pricing data.</p>

  const propData = draft[year][prop] as AnyRecord
  const rooms = Object.keys(propData).filter((k) => k !== 'extra_services')
  const extras = (propData.extra_services ?? {}) as AnyRecord

  const patchTier = (room: string, tier: string, value: number) =>
    setDraft((prev) => {
      const next = clone(prev)
      if (!next[year][prop][room].price_tiers) next[year][prop][room].price_tiers = {}
      next[year][prop][room].price_tiers[tier] = value
      return next
    })
  const patchRoomField = (room: string, field: string, value: number) =>
    setDraft((prev) => {
      const next = clone(prev)
      next[year][prop][room][field] = value
      return next
    })
  const patchExtra = (field: string, value: number) =>
    setDraft((prev) => {
      const next = clone(prev)
      if (!next[year][prop].extra_services) next[year][prop].extra_services = {}
      next[year][prop].extra_services[field] = value
      return next
    })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <label className="text-xs text-gray-500">
          Year
          <select value={year} onChange={(e) => setYear(e.target.value)} className={`${inputClass} mt-1`}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-gray-500">
          Property
          <select value={prop} onChange={(e) => setProp(e.target.value)} className={`${inputClass} mt-1`}>
            {properties.map((pn) => (
              <option key={pn} value={pn}>
                {pn}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <p className="mb-2 text-xs text-gray-500">Prices exclude VAT (applied automatically per booking dates).</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                <th className="pb-2">Room</th>
                {TIER_KEYS.map((t) => (
                  <th key={t} className="w-20 pb-2">
                    {t}n
                  </th>
                ))}
                <th className="w-24 pb-2">End clean</th>
                <th className="w-24 pb-2">Extra pers.</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((room) => {
                const r = propData[room] as AnyRecord
                const tiers = (r.price_tiers ?? {}) as AnyRecord
                return (
                  <tr key={room} className="border-t border-gray-100">
                    <td className="py-1 pr-2 text-gray-700">{room}</td>
                    {TIER_KEYS.map((t) => (
                      <td key={t} className="py-1 pr-1">
                        <input type="number" step="0.01" value={tiers[t] ?? 0} onChange={(e) => patchTier(room, t, Number(e.target.value))} className={inputClass} />
                      </td>
                    ))}
                    <td className="py-1 pr-1">
                      <input type="number" step="0.01" value={r.end_cleaning ?? 0} onChange={(e) => patchRoomField(room, 'end_cleaning', Number(e.target.value))} className={inputClass} />
                    </td>
                    <td className="py-1 pr-1">
                      <input type="number" step="0.01" value={r.extra_person_cost ?? 0} onChange={(e) => patchRoomField(room, 'extra_person_cost', Number(e.target.value))} className={inputClass} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-gray-500">Property services</h4>
        <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-3">
          {Object.keys(extras).map((k) =>
            typeof extras[k] === 'number' ? (
              <label key={k} className="text-xs text-gray-500">
                {k}
                <input type="number" step="0.01" value={extras[k]} onChange={(e) => patchExtra(k, Number(e.target.value))} className={inputClass} />
              </label>
            ) : null,
          )}
        </div>
      </div>

      <SaveBar saving={saving} onSave={() => onSave(draft)} />
    </div>
  )
}

function JsonEditor({ data, saving, onSave }: { data: AnyRecord; saving: boolean; onSave: (d: AnyRecord) => void }) {
  const [text, setText] = useState(() => JSON.stringify(data, null, 2))
  const [parseError, setParseError] = useState<string | null>(null)
  useEffect(() => setText(JSON.stringify(data, null, 2)), [data])

  const handleSave = () => {
    let parsed: AnyRecord
    try {
      parsed = JSON.parse(text)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : 'Invalid JSON')
      return
    }
    setParseError(null)
    onSave(parsed)
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Discount rules are edited as raw JSON (the full rule builder was not ported; discounts are currently disabled globally).
        Keep the top-level <code>presets</code> and <code>global_settings</code> keys.
      </p>
      {parseError ? <p className="rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">{parseError}</p> : null}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        className="h-96 w-full rounded-lg border border-gray-200 p-3 font-mono text-xs"
      />
      <SaveBar saving={saving} onSave={handleSave} />
    </div>
  )
}
