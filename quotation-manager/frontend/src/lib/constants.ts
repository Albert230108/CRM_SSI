// Property -> rooms and per-room guest capacity, ported from the desktop
// Quotation Manager (Python-EmailQuotation-1/src/interface.py PROPERTY_ROOMS /
// ROOM_CAPACITY). Used for the occupancy indicator and the New Quotation
// property/room pickers.

export const PROPERTY_ROOMS: Record<string, string[]> = {
  'Central-Day Inn': ['Studio 1', 'Studio 2', 'Studio 3', 'Studio 4', 'Studio 5', 'Studio 6'],
  'Ensche-Day Inn': ['Room 1', 'Room 2', 'Room 3', 'Room 4', 'Room 5'],
  'Guest information': ['Under Request'],
  'Hoogstraat 69': ['Ground floor', 'Upper floor'],
  Blekerstraat: ['House'],
  Atjehstraat: ['Duplex Apartment'],
}

// Maximum guests per room. "Under Request" (99) means no practical limit.
export const ROOM_CAPACITY: Record<string, number> = {
  'Studio 1': 2,
  'Studio 2': 1,
  'Studio 3': 2,
  'Studio 4': 2,
  'Studio 5': 1,
  'Studio 6': 1,
  'Room 1': 1,
  'Room 2': 2,
  'Room 3': 2,
  'Room 4': 2,
  'Room 5': 2,
  'Ground floor': 2,
  'Upper floor': 2,
  House: 5,
  'Duplex Apartment': 4,
  'Under Request': 99,
}

// Room name -> Beds24 roomId, needed when creating a new booking.
export const ROOM_ID_MAPPING: Record<string, number> = {
  House: 271050,
  'Studio 1': 262377,
  'Studio 2': 262375,
  'Studio 3': 262379,
  'Studio 4': 262376,
  'Studio 5': 262380,
  'Studio 6': 262378,
  'Room 1': 262576,
  'Room 2': 262578,
  'Room 3': 262579,
  'Room 4': 262580,
  'Room 5': 262581,
  'Under Request': 564014,
  'Ground floor': 389957,
  'Upper floor': 564867,
  'Duplex Apartment': 286739,
}

// Nights above which the long-stay deposit / 0% VAT rules kick in.
export const LONG_STAY_DEPOSIT_NIGHT_THRESHOLD = 183
export const LONG_STAY_DEPOSIT_DEFAULT = 1500

// Beds24 booking payloads carry roomId, not a room name - the editor needs the
// reverse of ROOM_ID_MAPPING to prefill the room dropdown from an existing booking.
export function roomNameForId(roomId: number | string | null | undefined): string {
  if (roomId === null || roomId === undefined || roomId === '') return ''
  const numericId = typeof roomId === 'string' ? Number(roomId) : roomId
  const entry = Object.entries(ROOM_ID_MAPPING).find(([, id]) => id === numericId)
  return entry ? entry[0] : ''
}

// The Beds24 room id for a room name, per ROOM_ID_MAPPING - used to send room_id to the
// PDF generator so the studio/room "pictures & information" link renders as a clickable link.
export function roomIdForName(roomName: string): number | null {
  if (!roomName) return null
  const id = ROOM_ID_MAPPING[roomName]
  return typeof id === 'number' ? id : null
}

// The property a given room belongs to, per PROPERTY_ROOMS - used to prefill the
// property dropdown once the room is known but the booking's own propertyName is blank.
export function propertyForRoom(roomName: string): string {
  if (!roomName) return ''
  const entry = Object.entries(PROPERTY_ROOMS).find(([, rooms]) => rooms.includes(roomName))
  return entry ? entry[0] : ''
}
