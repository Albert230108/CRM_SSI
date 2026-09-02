from datetime import date, timedelta

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
