"""
Builds the installment payment schedule for a quotation, ported from the
desktop Quotation Manager's add_payment_plan() /
manage_security_deposit_refund_in_table() (Python-EmailQuotation-1/src/interface.py).
The web port previously had no payment-plan generation at all - payments were
read-only, "managed via the booking itself".

Given the current charge lines, the security deposit, the stay dates, and a
requested installment count (1-24), it emits:

- 1 installment  -> a single "Full period + City Tax(+ Deposit)" row for the
  whole obligation.
- N installments -> a first "Confirms booking" row (deposit + end cleaning +
  administration costs), then N-1 equal "Rental Period + city tax" rows with
  any rounding remainder folded into the last one.
- A negative "Refund of Deposit ..." row (due check-out + 7 days) whenever the
  deposit is positive.

Due dates mirror the desktop schedule: 1st = today+2 (single) or today+4
(multi), 2nd = check-in, and each subsequent installment one month after the
previous, clamped to the check-out date.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

MIN_INSTALLMENTS = 1
MAX_INSTALLMENTS = 24

_DATE_FMT = "%d-%b-%Y"


class PaymentPlanError(Exception):
    """Raised when a payment plan can't be built (e.g. check-out before check-in)."""


@dataclass
class ChargeLine:
    description: str
    qty: float
    amount: float

    @property
    def line_total(self) -> float:
        return round(self.qty * self.amount, 2)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _add_months(d: date, months: int) -> date:
    """Add whole months to a date, clamping the day to the last valid day of the
    target month (matches dateutil.relativedelta's month behaviour without the
    extra dependency)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # Last day of the target month.
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _line_total_by_description(charges: list[ChargeLine], target: str) -> float:
    for charge in charges:
        if charge.description.strip().lower() == target:
            return charge.line_total
    return 0.0


def _total_charges(charges: list[ChargeLine]) -> float:
    # Exclude any explicit "security deposit" charge line: the deposit is tracked
    # separately and added back in build_payment_plan, so counting it here too
    # would double it.
    return round(
        sum(c.line_total for c in charges if c.description.strip().lower() != "security deposit"),
        2,
    )


def _due_dates(check_in: date, check_out: date, n_installments: int, today: date) -> list[date]:
    if n_installments == 1:
        return [today + timedelta(days=2)]

    dates = [today + timedelta(days=4), check_in]
    for i in range(2, n_installments):
        due = _add_months(check_in, i - 1)
        if due > check_out:
            due = check_out
        dates.append(due)
    return dates


def build_payment_plan(
    charges: list[ChargeLine],
    check_in: date,
    check_out: date,
    installments: int = 1,
    security_deposit: float = 0.0,
    today: Optional[date] = None,
) -> dict[str, Any]:
    if check_out <= check_in:
        raise PaymentPlanError("check_out must be after check_in")

    today = today or date.today()
    deposit = max(0.0, round(security_deposit, 2))
    n_installments = max(MIN_INSTALLMENTS, min(int(installments), MAX_INSTALLMENTS))

    total_charges = round(_total_charges(charges) + deposit, 2)
    end_cleaning = _line_total_by_description(charges, "end cleaning")
    admin_costs = _line_total_by_description(charges, "administration costs")

    due_dates = _due_dates(check_in, check_out, n_installments, today)
    due_strs = [d.strftime(_DATE_FMT) for d in due_dates]

    payments: list[dict[str, Any]] = []

    if n_installments == 1:
        deposit_text = " + Deposit" if deposit > 0 else ""
        description = f"Installment 1 - Full period + City Tax{deposit_text}; due: {due_strs[0]}"
        payments.append(_installment_row(description, total_charges))
    else:
        first_amount = round(deposit + end_cleaning + admin_costs, 2)
        deposit_prefix = "deposit+" if deposit > 0 else ""
        desc1 = (
            f"Installment 1 - Confirms booking ({deposit_prefix}End cleaning + "
            f"Administration costs); due: {due_strs[0]}"
        )
        payments.append(_installment_row(desc1, first_amount))

        rental_total = round(total_charges - first_amount, 2)
        num_rental_installments = n_installments - 1
        per_rental = round(rental_total / num_rental_installments, 2) if num_rental_installments else 0.0

        for idx in range(1, n_installments):
            if idx == n_installments - 1:
                paid_so_far = round(per_rental * (num_rental_installments - 1), 2)
                this_rental = round(rental_total - paid_so_far, 2)
            else:
                this_rental = per_rental
            nth = _ordinal(idx)
            description = f"Installment {idx + 1} - {nth} Rental Period + city tax; due: {due_strs[idx]}"
            payments.append(_installment_row(description, this_rental))

    if deposit > 0:
        refund_due = (check_out + timedelta(days=7)).strftime(_DATE_FMT)
        refund_desc = f"Refund of Deposit (Provided No Damages Are Present); due: {refund_due}"
        payments.append(
            {
                "kind": "deposit_refund",
                "description": refund_desc,
                "status": "not paid",
                "qty": 1.0,
                "amount": round(-deposit, 2),
                "vat_rate": 0.0,
            }
        )

    return {
        "installments": n_installments,
        "total_charges": total_charges,
        "payments": payments,
    }


def _installment_row(description: str, amount: float) -> dict[str, Any]:
    return {
        "kind": "installment",
        "description": description,
        "status": "not paid",
        "qty": 1.0,
        "amount": round(amount, 2),
        "vat_rate": 0.0,
    }
