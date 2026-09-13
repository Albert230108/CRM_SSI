import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiGet, apiPut } from '../lib/apiClient'
import { LONG_STAY_DEPOSIT_DEFAULT } from '../lib/constants'

type TabKey = 'admin-costs' | 'prices' | 'pdf-texts'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'admin-costs', label: 'Admin costs' },
  { key: 'prices', label: 'Price tiers' },
  { key: 'pdf-texts', label: 'PDF texts' },
]

type AnyRecord = Record<string, any>

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value))
}

const inputClass = 'w-full rounded border border-gray-200 px-2 py-1 text-sm'
const EXTRA_KEYS = ['deposit', 'city_tax', 'municipality_cost', 'long_stay_deposit']
const EXTRA_LABELS: Record<string, string> = {
  deposit: 'Deposit',
  city_tax: 'City tax',
  municipality_cost: 'Municipality cost',
  long_stay_deposit: 'Long-stay deposit (>183n)',
}
// The displayed default for an unset extra_services field. Long-stay deposit shows €1500 (the
// same fallback resolveConfiguredDeposit uses) rather than 0, so a blank field means "use €1500".
const extraDefault = (key: string): number => (key === 'long_stay_deposit' ? LONG_STAY_DEPOSIT_DEFAULT : 0)

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
      ) : tab === 'prices' ? (
        <PriceTiersEditor data={data} saving={saving} onSave={save} />
      ) : (
        <PdfTextsEditor data={data} saving={saving} onSave={save} />
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

// Prices are shaped: property -> { extra_services, rooms: { room -> { end_cleaning, extra_person_cost,
// price_ranges: [{ start, end, price_tiers: {nights: price}, extra_services? }] } } }.
function PriceTiersEditor({ data, saving, onSave }: { data: AnyRecord; saving: boolean; onSave: (d: AnyRecord) => void }) {
  const [draft, setDraft] = useState<AnyRecord>(() => clone(data))
  useEffect(() => setDraft(clone(data)), [data])

  // Skip the top-level `last_updated` string that config_store writes on every save - it isn't a
  // property and must not appear in the picker.
  const properties = Object.keys(draft).filter((k) => k !== 'last_updated' && draft[k] && typeof draft[k] === 'object')
  const [prop, setProp] = useState(properties[0] ?? '')
  useEffect(() => {
    if (!properties.includes(prop)) setProp(properties[0] ?? '')
  }, [properties, prop])

  if (!prop) return <p className="text-sm text-gray-500">No pricing data.</p>

  const propData = draft[prop] as AnyRecord
  const rooms = Object.keys(propData.rooms ?? {})

  const mutate = (fn: (next: AnyRecord) => void) =>
    setDraft((prev) => {
      const next = clone(prev)
      fn(next)
      return next
    })

  const rangesOf = (root: AnyRecord, room: string): AnyRecord[] => root[prop].rooms[room].price_ranges ?? []

  const addRange = (room: string) =>
    mutate((next) => {
      const r = next[prop].rooms[room]
      r.price_ranges = r.price_ranges ?? []
      r.price_ranges.push({ start: '2026-01-01', end: '2026-12-31', price_tiers: { '7': 0 } })
    })
  const removeRange = (room: string, i: number) =>
    mutate((next) => {
      rangesOf(next, room).splice(i, 1)
    })
  const patchRangeDate = (room: string, i: number, field: 'start' | 'end', value: string) =>
    mutate((next) => {
      rangesOf(next, room)[i][field] = value
    })
  const patchTier = (room: string, i: number, nightsKey: string, price: number) =>
    mutate((next) => {
      rangesOf(next, room)[i].price_tiers[nightsKey] = price
    })
  const renameTier = (room: string, i: number, oldKey: string, newKey: string) =>
    mutate((next) => {
      const tiers = rangesOf(next, room)[i].price_tiers
      if (!newKey || tiers[newKey] !== undefined) return
      tiers[newKey] = tiers[oldKey]
      delete tiers[oldKey]
    })
  const addTier = (room: string, i: number) =>
    mutate((next) => {
      const tiers = rangesOf(next, room)[i].price_tiers
      let k = 1
      while (tiers[String(k)] !== undefined) k += 1
      tiers[String(k)] = 0
    })
  const removeTier = (room: string, i: number, key: string) =>
    mutate((next) => {
      delete rangesOf(next, room)[i].price_tiers[key]
    })
  const patchRangeExtra = (room: string, i: number, key: string, value: string) =>
    mutate((next) => {
      const rng = rangesOf(next, room)[i]
      rng.extra_services = rng.extra_services ?? {}
      if (value === '') delete rng.extra_services[key]
      else rng.extra_services[key] = Number(value)
    })
  const patchRoomField = (room: string, field: string, value: number) =>
    mutate((next) => {
      next[prop].rooms[room][field] = value
    })
  const patchPropertyExtra = (key: string, value: number) =>
    mutate((next) => {
      next[prop].extra_services = next[prop].extra_services ?? {}
      next[prop].extra_services[key] = value
    })

  const propExtras = (propData.extra_services ?? {}) as AnyRecord

  return (
    <div className="space-y-3">
      <label className="text-xs text-gray-500">
        Property
        <select value={prop} onChange={(e) => setProp(e.target.value)} className={`${inputClass} mt-1 max-w-xs`}>
          {properties.map((pn) => (
            <option key={pn} value={pn}>
              {pn}
            </option>
          ))}
        </select>
      </label>

      <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">Property default services (excl. VAT)</h4>
        <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
          {EXTRA_KEYS.map((k) => (
            <label key={k} className="text-xs text-gray-500">
              {EXTRA_LABELS[k] ?? k}
              <input type="number" step="0.01" value={propExtras[k] ?? extraDefault(k)} onChange={(e) => patchPropertyExtra(k, Number(e.target.value))} className={inputClass} />
            </label>
          ))}
        </div>
        <p className="mt-1 text-[11px] text-gray-400">A date range can override any of these below; otherwise the property default applies. Long-stay deposit applies when a stay is over 183 nights; leave it at €{LONG_STAY_DEPOSIT_DEFAULT} unless this property differs.</p>
      </div>

      {rooms.map((room) => {
        const r = propData.rooms[room] as AnyRecord
        const ranges = (r.price_ranges ?? []) as AnyRecord[]
        return (
          <div key={room} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-900">{room}</h3>
              <div className="flex gap-3">
                <label className="text-xs text-gray-500">
                  End clean
                  <input type="number" step="0.01" value={r.end_cleaning ?? 0} onChange={(e) => patchRoomField(room, 'end_cleaning', Number(e.target.value))} className={`${inputClass} w-24`} />
                </label>
                <label className="text-xs text-gray-500">
                  Extra pers.
                  <input type="number" step="0.01" value={r.extra_person_cost ?? 0} onChange={(e) => patchRoomField(room, 'extra_person_cost', Number(e.target.value))} className={`${inputClass} w-24`} />
                </label>
              </div>
            </div>

            <div className="mt-3 space-y-3">
              {ranges.map((rng, i) => {
                const tiers = (rng.price_tiers ?? {}) as AnyRecord
                const extra = (rng.extra_services ?? {}) as AnyRecord
                return (
                  <div key={i} className="rounded-xl border border-gray-100 bg-gray-50/60 p-3">
                    <div className="flex flex-wrap items-end gap-3">
                      <label className="text-xs text-gray-500">
                        From
                        <input type="date" value={rng.start ?? ''} onChange={(e) => patchRangeDate(room, i, 'start', e.target.value)} className={`${inputClass} mt-1`} />
                      </label>
                      <label className="text-xs text-gray-500">
                        To
                        <input type="date" value={rng.end ?? ''} onChange={(e) => patchRangeDate(room, i, 'end', e.target.value)} className={`${inputClass} mt-1`} />
                      </label>
                      <button type="button" onClick={() => removeRange(room, i)} className="text-xs text-rose-500 hover:text-rose-700">
                        Remove range
                      </button>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-2">
                      {Object.keys(tiers)
                        .sort((a, b) => Number(a) - Number(b))
                        .map((key) => (
                          <div key={key} className="flex items-center gap-1 rounded-lg border border-gray-200 bg-white px-2 py-1">
                            <input
                              type="number"
                              value={key}
                              onChange={(e) => renameTier(room, i, key, e.target.value)}
                              className="w-12 rounded border border-gray-200 px-1 py-0.5 text-xs"
                              title="Nights"
                            />
                            <span className="text-[11px] text-gray-400">n €</span>
                            <input
                              type="number"
                              step="0.01"
                              value={tiers[key] ?? 0}
                              onChange={(e) => patchTier(room, i, key, Number(e.target.value))}
                              className="w-20 rounded border border-gray-200 px-1 py-0.5 text-xs"
                              title="Price/night"
                            />
                            <button type="button" onClick={() => removeTier(room, i, key)} className="text-xs text-rose-400 hover:text-rose-600" title="Remove tier">
                              ×
                            </button>
                          </div>
                        ))}
                      <button type="button" onClick={() => addTier(room, i)} className="rounded-lg border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100">
                        + Tier
                      </button>
                    </div>

                    <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
                      {EXTRA_KEYS.map((k) => (
                        <label key={k} className="text-[11px] text-gray-400">
                          {EXTRA_LABELS[k] ?? k} override
                          <input
                            type="number"
                            step="0.01"
                            value={extra[k] ?? ''}
                            placeholder="default"
                            onChange={(e) => patchRangeExtra(room, i, k, e.target.value)}
                            className={inputClass}
                          />
                        </label>
                      ))}
                    </div>
                  </div>
                )
              })}
              <button type="button" onClick={() => addRange(room)} className="rounded-lg border border-gray-300 px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50">
                + Add date range
              </button>
            </div>
          </div>
        )
      })}

      <SaveBar saving={saving} onSave={() => onSave(draft)} />
    </div>
  )
}

// Standard boilerplate texts printed on every quotation PDF (company header, conditions,
// footer, deposit/misc notes). Shaped { texts: { key: string } } - see backend
// app/services/pdf_texts.py for the defaults and where each key renders in the PDF.
const PDF_TEXT_FIELDS: { key: string; label: string; hint: string; rows: number }[] = [
  { key: 'header_title', label: 'Header title', hint: 'Large title at the top of the PDF (default: "Quotation").', rows: 1 },
  { key: 'company_info', label: 'Company info block', hint: 'Top-right of the header. Supports <b>, <br/> and <font size=\'7\'> tags.', rows: 4 },
  { key: 'total_prices_header', label: '"Total prices" section header', rows: 1, hint: '' },
  { key: 'deposit_refund_note', label: 'Deposit refund note', hint: 'Small note shown under the deposit line.', rows: 1 },
  { key: 'conditions', label: 'Conditions paragraph', hint: 'Printed near the bottom of the PDF, above the footer.', rows: 5 },
  { key: 'footer', label: 'Footer', hint: 'IBAN/BIC/contact line. Use a blank line to start a new footer line.', rows: 3 },
]

function PdfTextsEditor({ data, saving, onSave }: { data: AnyRecord; saving: boolean; onSave: (d: AnyRecord) => void }) {
  const [draft, setDraft] = useState<AnyRecord>(() => clone(data))
  useEffect(() => setDraft(clone(data)), [data])
  const texts = (draft.texts ?? {}) as AnyRecord

  const patch = (key: string, value: string) =>
    setDraft((prev) => {
      const next = clone(prev)
      next.texts = next.texts ?? {}
      next.texts[key] = value
      return next
    })

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">These texts appear on every generated quotation PDF. Tenant-specific details (name, dates, amounts) are not edited here.</p>
      {PDF_TEXT_FIELDS.map((field) => (
        <div key={field.key} className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <label className="text-xs font-semibold text-gray-700">
            {field.label}
            <textarea
              value={texts[field.key] ?? ''}
              onChange={(e) => patch(field.key, e.target.value)}
              rows={field.rows}
              className={`${inputClass} mt-1 font-normal`}
            />
          </label>
          {field.hint ? <p className="mt-1 text-[11px] text-gray-400">{field.hint}</p> : null}
        </div>
      ))}
      <SaveBar saving={saving} onSave={() => onSave(draft)} />
    </div>
  )
}
