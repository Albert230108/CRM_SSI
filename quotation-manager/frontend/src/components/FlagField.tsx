import { FLAG_OPTIONS } from '../lib/constants'

interface FlagFieldProps {
  value: string
  onChange: (value: string) => void
}

/**
 * Beds24 booking flag dropdown shared by the quotation editor and New Quotation. A booking can
 * already carry a flag that isn't one of FLAG_OPTIONS (set by hand in Beds24) - it is kept as an
 * extra option so opening and re-sending the quotation doesn't silently wipe it.
 */
export default function FlagField({ value, onChange }: FlagFieldProps) {
  const options = FLAG_OPTIONS.includes(value) ? FLAG_OPTIONS : [...FLAG_OPTIONS, value]
  return (
    <label className="text-xs text-gray-500">
      Flag
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm"
      >
        {options.map((option) => (
          <option key={option || 'none'} value={option}>
            {option || '(none)'}
          </option>
        ))}
      </select>
    </label>
  )
}
