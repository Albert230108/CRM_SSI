import pytest

from app.services import vat


def test_gross_amount_matches_live_beds24_data():
    # Real booking (id 92234840, Sep 2026): Studio 6's config 7-night tier is
    # ex-VAT ~58.68 but the invoice item Beds24 actually holds is amount=71.00
    # vatRate=21 - this is the conversion that must reproduce that.
    assert vat.gross_amount(58.67769, 21) == 71.0


def test_gross_amount_admin_min_max():
    assert vat.gross_amount(95.04132, 21) == 115.0
    assert vat.gross_amount(219.00826, 21) == 265.0


def test_gross_amount_is_identity_at_zero_vat():
    assert vat.gross_amount(42.5, 0) == 42.5


def test_net_amount_reverses_gross_amount():
    gross = vat.gross_amount(58.67769, 21)
    assert vat.net_amount(gross, 21) == round(58.67769, 2)


def test_included_vat_matches_gross_minus_net():
    gross = 71.0
    assert vat.included_vat(gross, 21) == round(gross - vat.net_amount(gross, 21), 2)
    assert vat.included_vat(gross, 21) == pytest.approx(12.32, abs=0.01)


def test_included_vat_is_zero_at_zero_rate():
    assert vat.included_vat(42.5, 0) == 0.0
