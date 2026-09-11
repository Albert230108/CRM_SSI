import { PROPERTY_ROOMS } from '../lib/constants'

interface PropertyRoomFieldsProps {
  propertyName: string
  roomName: string
  onPropertyChange: (property: string) => void
  onRoomChange: (room: string) => void
  className?: string
}

const inputClass = 'mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm'

// A single select can't carry two values, so each option encodes property+room. The unit
// separator (U+241F) can't appear in a property/room name, so it round-trips unambiguously.
const SEP = '␟'
const encode = (property: string, room: string) => `${property}${SEP}${room}`
const decode = (value: string): [string, string] => {
  const [property = '', room = ''] = value.split(SEP)
  return [property, room]
}

/**
 * Combined property+room picker shared by the quotation editor and New Quotation: one grouped
 * dropdown with an optgroup per property and its rooms as options. Both a booking loaded from
 * Beds24 and a stored tenant record can carry a property/room name that isn't one of
 * PROPERTY_ROOMS' known values (a typo, a since-renamed room, ...) - rather than silently
 * swapping it for something else, an unrecognized current selection is kept as an extra
 * option so nothing is lost or changed out from under the user.
 */
export default function PropertyRoomFields({
  propertyName,
  roomName,
  onPropertyChange,
  onRoomChange,
  className,
}: PropertyRoomFieldsProps) {
  const known = PROPERTY_ROOMS[propertyName]?.includes(roomName) ?? false
  const hasSelection = Boolean(propertyName || roomName)

  const handleChange = (value: string) => {
    if (!value) return
    const [property, room] = decode(value)
    onPropertyChange(property)
    onRoomChange(room)
  }

  return (
    <label className={`text-xs text-gray-500 ${className ?? ''}`}>
      Property &amp; room
      <select
        value={hasSelection ? encode(propertyName, roomName) : ''}
        onChange={(e) => handleChange(e.target.value)}
        className={inputClass}
      >
        {!hasSelection ? <option value="">Select property &amp; room…</option> : null}
        {/* Keep an out-of-list current selection visible instead of dropping it. */}
        {hasSelection && !known ? (
          <option value={encode(propertyName, roomName)}>
            {propertyName || '(no property)'} — {roomName || '(no room)'}
          </option>
        ) : null}
        {Object.entries(PROPERTY_ROOMS).map(([property, rooms]) => (
          <optgroup key={property} label={property}>
            {rooms.map((room) => (
              <option key={`${property}${SEP}${room}`} value={encode(property, room)}>
                {property} — {room}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  )
}
