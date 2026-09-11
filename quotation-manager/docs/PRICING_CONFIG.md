# Quotation Manager — pricing config authority (B5 / B7)

This is a **documentation-only** note (no config data was changed). It records which pricing
config is authoritative, where values are duplicated, and why some discount figures look odd,
so a future edit doesn't silently desync the two price sources. Confirm with the owner before
changing any production pricing data (`git`-tracked JSON under `backend/app/data/`).

## The config files

| File | Config key (Settings tab) | Role |
|------|---------------------------|------|
| `NewCombinedPrices.json` | `prices` | **Authoritative.** Per year → property → room: `price_tiers` (7/14/30/60/90-night rates, ex-VAT), `end_cleaning`, `extra_person_cost`, and per-property `extra_services` (`city_tax`, `municipality_cost`, `deposit`). `charge_builder` prices accommodation straight from `price_tiers`. |
| `base_prices.json` | `base-prices` | **Legacy duplicate.** `properties.<prop>.<room>.base_price` is a copy of the corresponding `price_tiers["7"]` in `NewCombinedPrices.json` (e.g. Central-Day Inn / Studio 1 = `58.67769` in both). Read only by `discount_engine.get_base_price`, which is part of the discount system. |
| `discount_rules.json` | `discount-rules` | Discount presets + `global_settings.enabled`. |
| `admin_costs.json` | `admin-costs` | Per-property admin `admin_percentage` / `admin_min` / `admin_max`. |

## B7 — base-price duplication (authority + desync risk)

- The **7-night tier in `NewCombinedPrices.json` is the single authoritative base price** for real
  quotations. `charge_builder` never reads `base_prices.json`.
- `base_prices.json` restates that same 7-night value. It feeds only
  `discount_engine.get_base_price` (which itself falls back to the NCP 7-night tier when a room is
  missing from `base_prices.json`).
- **Desync risk:** editing the 7-night tier in the `prices` Settings tab **without** also editing
  `base-prices` (or vice-versa) leaves the two disagreeing. Today this only affects the discount
  system's *display* (see B5), not the charges on a quotation — because the discount system is
  disabled. It would matter if the discount system is ever re-enabled.
- **Recommendation (needs owner sign-off before any data edit):** treat the NCP 7-night tier as the
  source of truth and either (a) stop shipping `base_prices.json` and let `get_base_price` always
  fall back to the NCP tier, or (b) regenerate `base_prices.json` from the NCP tiers whenever prices
  change. Do **not** hand-edit one without the other.

## B5 — discount precision / "weird 9.99-type values"

- `discount_rules.json` → `global_settings.enabled = false`. **The discount system is disabled**, so
  a quotation's accommodation price is exactly the applicable `price_tiers` value — the "base price"
  equals the 7-night tier and no big-discount logic runs. Keep it disabled unless the owner asks
  otherwise; nothing here changes it.
- The only per-night discount that still surfaces is the **Long Stay Discount** charge line, computed
  in `charge_builder` as `min(0, discounted_price − rack)` per VAT year on the 5-dp ex-VAT config
  values. Because the config stores 5 decimals (e.g. `58.67769`), the raw delta carries long
  decimals; it is **rounded to 2 dp only at the charge-line output** (`charge_builder` line ~196),
  matching the "keep 5 dp internally, round at output" rule. That output rounding is what makes the
  displayed discount a clean 2-dp figure rather than a `…9.99…`-style value.
- The **"Check Price / Discount"** button surfaces figures from the (disabled) big-discount system
  via `get_base_price`; those are informational and do not affect the generated charges.

## Related, already-verified

- **Admin costs** (`admin_costs.calculate_admin_costs`) already compute in full precision and round
  once at the final ex-VAT figure (identical to the desktop app), then get grossed up per VAT rate —
  no separate cent-rounding change was needed (B4).
