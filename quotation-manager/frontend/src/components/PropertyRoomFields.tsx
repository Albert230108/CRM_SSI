import { PROPERTY_ROOMS } from '../lib/constants'

interface PropertyRoomFieldsProps {
  propertyName: string
  roomName: string
  onPropertyChange: (property: string) => void
  onRoomChange: (room: string) => void
  className?: string
}

const inputClass = 'mt-1 w-full rounded border border-gray-200 px-2 py-1 text-sm'

/**
 * Property + room selects shared by the quotation editor and New Quotation.
 * Both a booking loaded from Beds24 and a stored tenant record can carry a
 * property/room name that isn't one of PROPERTY_ROOMS' known values (a typo,
 * a since-renamed room, ...) - rather than silently swapping it for something
 * else, an unrecognized value is kept as an extra option so nothing is lost
 * or changed out from under the user.
 */
export default function PropertyRoomFields({
  propertyName,
  roomName,
  onPropertyChange,
  onRoomChange,
  className,
}: PropertyRoomFieldsProps) {
  const properties = Object.keys(PROPERTY_ROOMS)
  const propertyOptions = propertyName && !properties.includes(propertyName) ? [propertyName, ...properties] : properties

  const rooms = PROPERTY_ROOMS[propertyName] ?? []
  const roomOptions = roomName && !rooms.includes(roomName) ? [roomName, ...rooms] : rooms

  const handlePropertyChange = (value: string) => {
    onPropertyChange(value)
    // Only reset the room when it doesn't belong to the newly picked property -
    // switching property shouldn't silently clear a room the user just set.
    const nextRooms = PROPERTY_ROOMS[value] ?? []
    if (!nextRooms.includes(roomName)) {
      onRoomChange(nextRooms[0] ?? '')
    }
  }

  return (
    <>
      <label className={`text-xs text-gray-500 ${className ?? ''}`}>
        Property
        <select value={propertyName} onChange={(e) => handlePropertyChange(e.target.value)} className={inputClass}>
          {!propertyName ? <option value="">Select property…</option> : null}
          {propertyOptions.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <label className={`text-xs text-gray-500 ${className ?? ''}`}>
        Room
        <select value={roomName} onChange={(e) => onRoomChange(e.target.value)} className={inputClass}>
          {!roomName ? <option value="">Select room…</option> : null}
          {roomOptions.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
    </>
  )
}
