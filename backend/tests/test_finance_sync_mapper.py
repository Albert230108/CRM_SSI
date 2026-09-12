"""Regression tests for the shared Beds24 invoice-item -> Finance mapper.

Before this mapper existed, four call sites had their own copy of the loop and two of them
never persisted qty/unit_price/vat_rate/status, so the Tenant Info table rendered an em
dash in four of its six columns. See app/services/finance_sync.py.
"""

from decimal import Decimal

from app.models.finance import Finance
from app.models.tenant import Tenant
from app.services.finance_sync import (
    build_finance_rows,
    replace_tenant_finance_from_booking,
    resolve_placeholders,
)


def _tenant(db_session, booking_id: str) -> Tenant:
    tenant = Tenant(booking_id=booking_id, name=booking_id)
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _booking(booking_id: str = "MAP-1", **overrides) -> dict:
    booking = {
        "id": booking_id,
        "roomName": "Studio 3",
        "arrival": "2026-07-01",
        "departure": "2026-07-08",
        "invoiceItems": [
            {
                "type": "charge",
                "description": "Rent",
                "qty": 7,
                "amount": 65,
                "lineTotal": 455,
                "vatRate": 9,
                "status": "",
                "currency": "EUR",
            },
            {
                "type": "payment",
                "description": "Deposit",
                "qty": 1,
                "amount": -100,
                "lineTotal": -100,
                "vatRate": 0,
                "status": "not paid",
                "currency": "EUR",
            },
        ],
    }
    booking.update(overrides)
    return booking


def test_mapper_persists_every_display_column(db_session):
    """The four columns that used to render as an em dash must all be populated."""
    tenant = _tenant(db_session, "MAP-COLUMNS")
    replace_tenant_finance_from_booking(db_session, tenant, _booking())
    db_session.commit()

    rows = db_session.query(Finance).filter(Finance.tenant_id == tenant.id).order_by(Finance.id).all()
    assert len(rows) == 2

    charge, payment = rows
    assert charge.type == "charge"
    assert charge.qty == Decimal("7")
    assert charge.unit_price == Decimal("65")
    assert charge.vat_rate == Decimal("9")
    assert charge.amount == Decimal("455")
    assert charge.currency == "EUR"
    # Beds24 sends status="" on every charge, so NULL is the honest value here.
    assert charge.status is None

    assert payment.type == "payment"
    assert payment.qty == Decimal("1")
    assert payment.unit_price == Decimal("-100")
    assert payment.status == "not paid"


def test_mapper_prefers_beds24_line_total_over_recomputation():
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {"type": "charge", "qty": 3, "amount": "16.53", "lineTotal": "49.60", "description": "x"},
    ]))
    assert rows[0].amount == Decimal("49.60")


def test_mapper_recomputes_line_total_when_beds24_omits_it():
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {"type": "charge", "qty": 4, "amount": "10.50", "description": "x"},
    ]))
    assert rows[0].amount == Decimal("42.00")


def test_mapper_defaults_qty_and_vat_when_absent():
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {"type": "payment", "amount": "-50", "description": "x"},
    ]))
    assert rows[0].qty == Decimal("1")
    assert rows[0].vat_rate == Decimal("0")
    assert rows[0].unit_price == Decimal("-50")


def test_mapper_cleans_beds24_description_markup():
    """The live webhook used to store the raw description, leaking HTML and Beds24 tags."""
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {
            "type": "charge",
            "amount": 10,
            "description": 'Pay here <a href="http://x">now</a> ##NOLINK## [PAYLINK:100] &amp; more',
        },
    ]))
    description = rows[0].description
    assert "<a" not in description
    assert "##NOLINK##" not in description
    assert "PAYLINK" not in description
    assert "now" in description  # anchor text is kept, not deleted
    assert "&" in description  # HTML entity unescaped


def test_mapper_resolves_booking_placeholders():
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {"type": "charge", "amount": 10, "description": "[ROOMNAME1] [FIRSTNIGHT] - [LEAVINGDAY]"},
    ]))
    assert rows[0].description == "Studio 3 2026-07-01 - 2026-07-08"


def test_mapper_skips_non_charge_payment_types():
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {"type": "charge", "amount": 10, "description": "keep"},
        {"type": "note", "amount": 10, "description": "drop"},
        "not-a-dict",
    ]))
    assert [row.description for row in rows] == ["keep"]


def test_missing_invoice_items_key_leaves_existing_rows_untouched(db_session):
    """Regression: the quotation/auto-draft sync used to delete a tenant's whole finance
    breakdown whenever it ran against a payload that carried no invoiceItems."""
    tenant = _tenant(db_session, "MAP-NOWIPE")
    replace_tenant_finance_from_booking(db_session, tenant, _booking())
    db_session.commit()
    assert db_session.query(Finance).filter(Finance.tenant_id == tenant.id).count() == 2

    written = replace_tenant_finance_from_booking(db_session, tenant, {"id": "MAP-NOWIPE"})
    db_session.commit()

    assert written == 0
    rows = db_session.query(Finance).filter(Finance.tenant_id == tenant.id).all()
    assert len(rows) == 2
    assert rows[0].qty == Decimal("7")


def test_empty_invoice_items_list_clears_rows(db_session):
    """An explicitly empty list is a real "this booking has no lines" statement, unlike a
    missing key, so it must clear the rows."""
    tenant = _tenant(db_session, "MAP-EMPTY")
    replace_tenant_finance_from_booking(db_session, tenant, _booking())
    db_session.commit()

    replace_tenant_finance_from_booking(db_session, tenant, {"id": "MAP-EMPTY", "invoiceItems": []})
    db_session.commit()

    assert db_session.query(Finance).filter(Finance.tenant_id == tenant.id).count() == 0


def test_mapper_survives_unparseable_numbers():
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {"type": "charge", "qty": "n/a", "amount": None, "vatRate": "", "description": "odd"},
    ]))
    assert rows[0].qty == Decimal("1")
    assert rows[0].unit_price == Decimal("0")
    assert rows[0].vat_rate == Decimal("0")


def test_resolve_placeholders_leaves_unknown_tokens_alone():
    assert resolve_placeholders("[UNKNOWN] x", {"id": 1}) == "[UNKNOWN] x"


def test_amounts_are_quantized_to_two_decimals():
    """Beds24 sends JSON floats, so lineTotal and amount*qty both arrive with binary-float
    noise (e.g. -5025.120000000001) that must not reach the stored value."""
    rows = build_finance_rows(1, _booking(invoiceItems=[
        {"type": "charge", "qty": 304, "amount": -16.53, "lineTotal": -5025.120000000001, "description": "a"},
        {"type": "charge", "qty": 102, "amount": 3.39, "description": "b"},
    ]))
    assert rows[0].amount == Decimal("-5025.12")
    assert rows[1].amount == Decimal("345.78")
