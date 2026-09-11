"""C2 (Beds24 write): payment descriptions get Beds24's [PAYLINK: amount] tag on send/create,
which Beds24 expands into a real pay link server-side."""
from app.api.quotation import _apply_beds24_paylinks


def test_paylink_added_to_positive_payments_only():
    items = [
        {"type": "payment", "description": "Installment 1", "qty": 1, "amount": 500.0},
        {"type": "payment", "description": "Refund of Deposit", "qty": 1, "amount": -400.0},
        {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0},
    ]
    _apply_beds24_paylinks(items)
    assert items[0]["description"] == "Installment 1 [PAYLINK: 500.00]"
    assert "[PAYLINK:" not in items[1]["description"]  # negative
    assert "[PAYLINK:" not in items[2]["description"]  # charge


def test_paylink_respects_nolink_and_is_idempotent():
    disabled = [{"type": "payment", "description": "Deposit ##NOLINK##", "qty": 1, "amount": 200.0}]
    _apply_beds24_paylinks(disabled)
    assert "[PAYLINK:" not in disabled[0]["description"]
    assert disabled[0]["description"].endswith("##NOLINK##")

    # Re-sending an item that already carries a tag must not stack a second one.
    already = [{"type": "payment", "description": "Installment 1 [PAYLINK: 500.00]", "qty": 1, "amount": 500.0}]
    _apply_beds24_paylinks(already)
    assert already[0]["description"].count("[PAYLINK:") == 1


def test_paylink_strips_prior_html_anchor():
    items = [{
        "type": "payment",
        "description": 'Installment 1 <a href="https://beds24.com/bookpay.php?bookid=1&pay=500">Pay</a>',
        "qty": 1, "amount": 500.0,
    }]
    _apply_beds24_paylinks(items)
    assert "<a href" not in items[0]["description"]
    assert items[0]["description"] == "Installment 1 [PAYLINK: 500.00]"
