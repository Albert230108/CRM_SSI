// Pricing-config shape and resolution helpers shared by the editor and New Quotation pages.
// Mirrors the backend app.services.pricing_config (resolve_range / resolve_extra_services) closely
// enough to prefill the deposit client-side from /api/config/prices.

import { LONG_STAY_DEPOSIT_DEFAULT, LONG_STAY_DEPOSIT_NIGHT_THRESHOLD, propertyForRoom } from './constants'

export type ExtraServices = {
  deposit?: number
  city_tax?: number
  municipality_cost?: number
  // Optional per-property/range override for the long-stay (> 183 nights) deposit. When absent,
  // the long-stay deposit falls back to LONG_STAY_DEPOSIT_DEFAULT (€1500), matching the desktop.
  long_stay_deposit?: number
}
export type PriceRange = { start: string; end: string; price_tiers?: Record<string, number>; extra_services?: ExtraServices }
export type PricingRoom = { price_ranges?: PriceRange[] }
export type PricingProperty = { extra_services?: ExtraServices; rooms?: Record<string, PricingRoom> }
export type PricingConfig = Record<string, PricingProperty | undefined>

// The price range covering `iso` (YYYY-MM-DD), else the latest range starting on/before it, else
// the earliest - mirrors pricing_config.resolve_range on the backend.
export function resolveRange(room: PricingRoom | undefined, iso: string): PriceRange | undefined {
  const ranges = room?.price_ranges ?? []
  if (ranges.length === 0) return undefined
  const containing = ranges.find((r) => r.start <= iso && iso <= r.end)
  if (containing) return containing
  const earlier = ranges.filter((r) => r.start <= iso).sort((a, b) => a.start.localeCompare(b.start))
  return earlier.length ? earlier[earlier.length - 1] : [...ranges].sort((a, b) => a.start.localeCompare(b.start))[0]
}

// The deposit to prefill for the given property/room/check-in date. Resolves the property by name,
// falling back to the property the selected room belongs to (Beds24 sometimes sends a property name
// that isn't a config key). For a long stay (nights > 183) it returns the configured
// long_stay_deposit, else the €1500 default - matching the desktop's refresh_charges_table.
export function resolveConfiguredDeposit(
  config: PricingConfig | null,
  propertyName: string,
  roomName: string,
  checkIn: string,
  nights: number | null,
): number | null {
  if (!config) return null
  const prop = config[propertyName] ?? config[propertyForRoom(roomName)]
  if (!prop) return null
  const range = resolveRange(prop.rooms?.[roomName], checkIn || '')
  if (nights !== null && nights > LONG_STAY_DEPOSIT_NIGHT_THRESHOLD) {
    const longStay = range?.extra_services?.long_stay_deposit ?? prop.extra_services?.long_stay_deposit
    return typeof longStay === 'number' ? longStay : LONG_STAY_DEPOSIT_DEFAULT
  }
  const deposit = range?.extra_services?.deposit ?? prop.extra_services?.deposit
  return typeof deposit === 'number' ? deposit : null
}
