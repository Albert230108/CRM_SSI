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
