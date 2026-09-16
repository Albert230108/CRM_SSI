from datetime import date, datetime, timedelta

import pytest

from app.services import payment_plan
from app.services.payment_plan import ChargeLine


def _charges():
    # Accommodation 700, city tax 21, end cleaning 100, admin 50 -> 871 total.
    return [
        ChargeLine(description="Studio 1 - 01-Jun-2025 - 08-Jun-2025", qty=7, amount=100.0),
        ChargeLine(description="Citytax for 1 person(s)", qty=7, amount=3.0),
        ChargeLine(description="End cleaning", qty=1, amount=100.0),
        ChargeLine(description="Administration costs", qty=1, amount=50.0),
    ]


def test_single_installment_no_deposit():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 6, 8),
        installments=1,
        security_deposit=0.0,
        today=date(2025, 5, 1),
    )
    assert result["installments"] == 1
    assert result["total_charges"] == 871.0
    assert len(result["payments"]) == 1
    row = result["payments"][0]
    assert row["kind"] == "installment"
    assert row["amount"] == 871.0
    assert "Full period + City Tax" in row["description"]
    assert "Deposit" not in row["description"]
    assert "due: 03-May-2025" in row["description"]


def test_single_installment_with_deposit_adds_refund_row():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 6, 8),
        installments=1,
        security_deposit=300.0,
        today=date(2025, 5, 1),
    )
    # Total now includes the deposit.
    assert result["total_charges"] == 1171.0
    assert len(result["payments"]) == 2
    installment, refund = result["payments"]
    assert installment["amount"] == 1171.0
    assert "+ Deposit" in installment["description"]
    assert refund["kind"] == "deposit_refund"
    assert refund["amount"] == -300.0
    # check_out + 7 days.
    assert "due: 15-Jun-2025" in refund["description"]


def test_multi_installment_split_and_remainder():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=3,
        security_deposit=300.0,
        today=date(2025, 5, 1),
    )
    payments = result["payments"]
    # 3 installments + 1 refund row.
    assert len(payments) == 4
    installments = [p for p in payments if p["kind"] == "installment"]
    assert len(installments) == 3

    # First installment = deposit + end cleaning + admin = 300 + 100 + 50.
    assert installments[0]["amount"] == 450.0
    assert "Confirms booking" in installments[0]["description"]
    assert "deposit+" in installments[0]["description"]

    # Remaining two rental installments must sum to total - first.
    total = result["total_charges"]
    rental_sum = round(sum(p["amount"] for p in installments[1:]), 2)
    assert rental_sum == round(total - 450.0, 2)

    # Every installment carries a due date.
    assert all("due:" in p["description"] for p in installments)


def test_no_deposit_has_no_refund_row():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=4,
        security_deposit=0.0,
        today=date(2025, 5, 1),
    )
    assert all(p["kind"] != "deposit_refund" for p in result["payments"])


def test_installments_clamped_to_max():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2027, 6, 1),
        installments=99,
        today=date(2025, 5, 1),
    )
    assert result["installments"] == payment_plan.MAX_INSTALLMENTS


def test_checkout_before_checkin_raises():
    with pytest.raises(payment_plan.PaymentPlanError):
        payment_plan.build_payment_plan(
            charges=_charges(),
            check_in=date(2025, 6, 8),
            check_out=date(2025, 6, 1),
        )


def test_due_dates_never_go_backwards_when_checkin_is_in_the_past():
    # Regression: a booking quoted after its check-in date (e.g. a past/near
    # -term stay) used to produce Installment 2 due at check-in, earlier than
    # Installment 1's today-anchored due date.
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2026, 7, 3),
        check_out=date(2026, 7, 31),
        installments=3,
        security_deposit=0.0,
        today=date(2026, 9, 11),
    )
    due_dates = [p["description"].split("due: ")[1] for p in result["payments"] if p["kind"] == "installment"]
    parsed = [datetime.strptime(d, "%d-%b-%Y").date() for d in due_dates]
    assert parsed == sorted(parsed)


def test_add_months_clamps_day():
    # Jan 31 + 1 month -> Feb 28 (2025 is not a leap year).
    assert payment_plan._add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)


# --- endpoint tests ---


def test_build_payment_plan_endpoint(client, auth_headers):
    response = client.post(
        "/api/quotation/build-payment-plan",
        headers=auth_headers,
        json={
            "check_in": "2025-06-01",
            "check_out": "2025-09-01",
            "installments": 3,
            "security_deposit": 300.0,
            "charges": [
                {"description": "Studio 1 - stay", "qty": 7, "amount": 100.0},
                {"description": "End cleaning", "qty": 1, "amount": 100.0},
                {"description": "Administration costs", "qty": 1, "amount": 50.0},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["installments"] == 3
    assert len([p for p in body["payments"] if p["kind"] == "installment"]) == 3
    assert any(p["kind"] == "deposit_refund" for p in body["payments"])


def test_build_payment_plan_endpoint_requires_token(client):
    response = client.post(
        "/api/quotation/build-payment-plan",
        json={"check_in": "2025-06-01", "check_out": "2025-09-01", "installments": 1, "charges": []},
    )
    assert response.status_code in (401, 403)


def test_build_payment_plan_endpoint_bad_dates(client, auth_headers):
    response = client.post(
        "/api/quotation/build-payment-plan",
        headers=auth_headers,
        json={"check_in": "2025-06-08", "check_out": "2025-06-01", "installments": 1, "charges": []},
    )
    assert response.status_code == 400


# --- regenerating a plan without disturbing already-paid rows ---


def _paid_row(description: str, amount: float, status: str = "12-Sep-2026") -> "payment_plan.PaymentRow":
    from app.services.payment_plan import PaymentRow

    return PaymentRow(description=description, qty=1, amount=amount, status=status)


def _unpaid_row(description: str, amount: float) -> "payment_plan.PaymentRow":
    from app.services.payment_plan import PaymentRow

    return PaymentRow(description=description, qty=1, amount=amount, status="not paid")


def test_regenerate_keeps_paid_first_installment_and_splits_remainder():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=3,
        security_deposit=0.0,
        existing_payments=[_paid_row("Installment 1 - Confirms booking (End cleaning + Administration costs)", 150.0)],
        today=date(2025, 5, 1),
    )
    assert result["kept_count"] == 1
    assert result["paid_total"] == 150.0
    assert result["remaining"] == pytest.approx(871.0 - 150.0, abs=0.01)

    kept = [p for p in result["payments"] if p["kind"] == "kept"]
    assert len(kept) == 1
    assert kept[0]["amount"] == 150.0
    assert kept[0]["status"] == "12-Sep-2026"

    new_installments = [p for p in result["payments"] if p["kind"] == "installment"]
    assert len(new_installments) == 2
    assert new_installments[0]["description"].startswith("Installment 2 - 1st Rental Period")
    assert new_installments[1]["description"].startswith("Installment 3 - 2nd Rental Period")
    assert round(sum(p["amount"] for p in new_installments), 2) == pytest.approx(result["remaining"], abs=0.02)
    # New rows never fall due before the original today+4 anchor.
    for p in new_installments:
        due_str = p["description"].split("due: ")[1]
        assert datetime.strptime(due_str, "%d-%b-%Y").date() >= date(2025, 5, 1) + timedelta(days=4)


def test_regenerate_with_fewer_new_installments_than_paid_makes_one_remainder_row():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=1,  # total requested is now lower than what's already paid installments
        security_deposit=200.0,
        existing_payments=[_paid_row("Installment 1 - Confirms booking", 150.0)],
        today=date(2025, 5, 1),
    )
    new_installments = [p for p in result["payments"] if p["kind"] == "installment"]
    assert len(new_installments) == 1
    assert new_installments[0]["amount"] == pytest.approx(result["remaining"], abs=0.01)
    assert result["remaining"] > 0


def test_even_spread_dates_unpaid_installments_between_latest_paid_and_checkout():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=3,
        security_deposit=0.0,
        existing_payments=[_paid_row("Installment 1 - Confirms booking", 150.0, status="10-Jun-2025")],
        today=date(2025, 5, 1),
        even_spread=True,
    )
    new_installments = [p for p in result["payments"] if p["kind"] == "installment"]
    assert len(new_installments) == 2
    due_dates = [
        datetime.strptime(p["description"].split("due: ")[1], "%d-%b-%Y").date() for p in new_installments
    ]
    # Both new due dates fall strictly after the latest paid date and no later than check-out,
    # and they are spread out rather than clustered on the same day.
    for due in due_dates:
        assert date(2025, 6, 10) < due <= date(2025, 9, 1)
    assert due_dates[0] < due_dates[1]
    # Paid row and its amount/status are untouched.
    kept = [p for p in result["payments"] if p["kind"] == "kept"]
    assert kept[0]["amount"] == 150.0
    assert kept[0]["status"] == "10-Jun-2025"


def test_even_spread_false_reproduces_classic_due_dates():
    kwargs = dict(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=3,
        security_deposit=0.0,
        existing_payments=[_paid_row("Installment 1 - Confirms booking", 150.0, status="10-Jun-2025")],
        today=date(2025, 5, 1),
    )
    without_flag = payment_plan.build_payment_plan(**kwargs)
    explicit_false = payment_plan.build_payment_plan(**kwargs, even_spread=False)
    assert without_flag["payments"] == explicit_false["payments"]


def test_even_spread_falls_back_to_today_when_paid_status_unparseable():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=2,
        security_deposit=0.0,
        existing_payments=[_paid_row("Installment 1 - Confirms booking", 150.0, status="paid on arrival")],
        today=date(2025, 5, 1),
        even_spread=True,
    )
    new_installments = [p for p in result["payments"] if p["kind"] == "installment"]
    assert len(new_installments) == 1
    due = datetime.strptime(new_installments[0]["description"].split("due: ")[1], "%d-%b-%Y").date()
    assert date(2025, 5, 1) < due <= date(2025, 9, 1)


def test_regenerate_refunds_overpayment_instead_of_new_installments():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=3,
        security_deposit=0.0,
        existing_payments=[_paid_row("Installment 1 - Confirms booking", 1000.0)],
        today=date(2025, 5, 1),
    )
    assert result["remaining"] < 0
    assert not [p for p in result["payments"] if p["kind"] == "installment"]
    refunds = [p for p in result["payments"] if p["kind"] == "overpayment_refund"]
    assert len(refunds) == 1
    assert refunds[0]["amount"] == result["remaining"]
    assert refunds[0]["amount"] < 0
    assert "due:" in refunds[0]["description"]


def test_regenerate_balanced_adds_no_new_installment_but_keeps_deposit_refund():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=1,
        security_deposit=200.0,
        existing_payments=[_paid_row("Installment 1 - Confirms booking", 871.0 + 200.0)],
        today=date(2025, 5, 1),
    )
    assert result["remaining"] == pytest.approx(0.0, abs=0.01)
    assert not [p for p in result["payments"] if p["kind"] in ("installment", "overpayment_refund")]
    deposit_refunds = [p for p in result["payments"] if p["kind"] == "deposit_refund"]
    assert len(deposit_refunds) == 1
    assert deposit_refunds[0]["amount"] == -200.0


def test_regenerate_does_not_duplicate_an_already_kept_deposit_refund():
    result = payment_plan.build_payment_plan(
        charges=_charges(),
        check_in=date(2025, 6, 1),
        check_out=date(2025, 9, 1),
        installments=1,
        security_deposit=200.0,
        existing_payments=[
            _paid_row("Installment 1 - Confirms booking", 871.0 + 200.0),
            _paid_row("Refund of Deposit (Provided No Damages Are Present); due: 08-Sep-2025", -200.0),
        ],
        today=date(2025, 5, 1),
    )
    deposit_refunds = [p for p in result["payments"] if "refund of deposit" in p["description"].lower()]
    # Only the kept one - no fresh deposit_refund row appended on top of it.
    assert len(deposit_refunds) == 1
    assert deposit_refunds[0]["kind"] == "kept"


def test_regenerate_with_no_paid_rows_matches_fresh_plan():
    fresh = payment_plan.build_payment_plan(
        charges=_charges(), check_in=date(2025, 6, 1), check_out=date(2025, 9, 1),
        installments=3, security_deposit=0.0, today=date(2025, 5, 1),
    )
    regenerated = payment_plan.build_payment_plan(
        charges=_charges(), check_in=date(2025, 6, 1), check_out=date(2025, 9, 1),
        installments=3, security_deposit=0.0,
        existing_payments=[_unpaid_row("Installment 1 - Confirms booking", 150.0)],
        today=date(2025, 5, 1),
    )
    assert regenerated["kept_count"] == 0
    assert [p["amount"] for p in regenerated["payments"]] == [p["amount"] for p in fresh["payments"]]


def test_is_paid_treats_not_paid_and_blank_as_unpaid():
    assert payment_plan.is_paid("not paid") is False
    assert payment_plan.is_paid("Not Paid") is False
    assert payment_plan.is_paid("") is False
    assert payment_plan.is_paid(None) is False
    assert payment_plan.is_paid("12-Sep-2026") is True


def test_build_payment_plan_endpoint_with_existing_payments(client, auth_headers):
    response = client.post(
        "/api/quotation/build-payment-plan",
        headers=auth_headers,
        json={
            "check_in": "2025-06-01",
            "check_out": "2025-09-01",
            "installments": 3,
            "security_deposit": 0.0,
            "charges": [
                {"description": "Studio 1 - stay", "qty": 7, "amount": 100.0},
                {"description": "Citytax for 1 person(s)", "qty": 7, "amount": 3.0},
                {"description": "End cleaning", "qty": 1, "amount": 100.0},
                {"description": "Administration costs", "qty": 1, "amount": 50.0},
            ],
            "existing_payments": [
                {"description": "Installment 1 - Confirms booking", "qty": 1, "amount": 150.0, "status": "12-Sep-2026"}
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kept_count"] == 1
    kept = [p for p in body["payments"] if p["kind"] == "kept"]
    assert kept[0]["status"] == "12-Sep-2026"
    assert any(p["kind"] == "installment" for p in body["payments"])
