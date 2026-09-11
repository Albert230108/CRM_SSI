"""
VAT-inclusive/exclusive conversions.

All pricing config (base_prices.json, NewCombinedPrices.json price_tiers,
admin_costs.json min/max) is kept and edited VAT-EXCLUSIVE in Settings and in
every internal calculation (discount tiers, admin-cost percentage/clamping) -
that data model is unchanged.

Beds24 invoice-item amounts, however, are VAT-INCLUSIVE: a live Studio 6
booking holds amount=71.00 vatRate=21 where the ex-VAT config tier is 58.68.
So the *quotation form* - the charge lines a booking actually gets, the
payment plan built from them, the generated PDF, and what's pushed back to
Beds24 - must show/use gross (incl.-VAT) amounts. The gross-up happens once,
at the point a charge line is emitted onto the form (charge_builder); nothing
upstream of that (Settings, the pricing JSON, the discount engine) changes.
"""

from datetime import date

# 9% VAT applies to nights before this date, 21% from this date onward -
# matches pdf_service.split_booking_by_vat's boundary.
VAT_2026_START = date(2026, 1, 1)


def vat_rate_for_date(d: date) -> float:
    return 21.0 if d >= VAT_2026_START else 9.0


def gross_amount(net_amount: float, vat_rate: float) -> float:
    """Net (ex-VAT) amount -> gross (incl.-VAT) amount, e.g. 58.67769 @21% -> 71.00."""
    return round(net_amount * (1 + vat_rate / 100.0), 2)


def net_amount(gross_amount_value: float, vat_rate: float) -> float:
    """Gross (incl.-VAT) amount -> net (ex-VAT) amount."""
    return round(gross_amount_value / (1 + vat_rate / 100.0), 2)


def included_vat(gross_amount_value: float, vat_rate: float) -> float:
    """The VAT portion already included in a gross amount (gross - net)."""
    return round(gross_amount_value - net_amount(gross_amount_value, vat_rate), 2)
