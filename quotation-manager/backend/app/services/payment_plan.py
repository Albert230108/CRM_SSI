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

Regenerating a plan (build_payment_plan's existing_payments argument) never
touches a row that's already paid: Beds24 payment rows only carry a free-text
status ("not paid" or a date the tenant actually paid), so "paid" here means
exactly that - a non-empty status other than "not paid". Paid rows are kept
verbatim; only the remaining balance (new total minus what's already paid) is
re-split across new installments, or refunded if the new total came out lower
than what was already collected (e.g. the stay was shortened).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

MIN_INSTALLMENTS = 1
MAX_INSTALLMENTS = 24

_DATE_FMT = "%d-%b-%Y"
_ROUNDING_EPSILON = 0.005


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


@dataclass
class PaymentRow:
    """An existing payment row on the quotation, as passed back to a regeneration
    request. status is Beds24's free-text payment status field: "not paid", or the
    date the tenant actually paid (see is_paid)."""

    description: str
    qty: float
    amount: float
    status: str = "not paid"
    vat_rate: float = 0.0

    @property
    def line_total(self) -> float:
        return round(self.qty * self.amount, 2)


def is_paid(status: Optional[str]) -> bool:
    """A row is paid when its status is set to anything other than "not paid" -
    in practice, tenants/staff replace "not paid" with the date it was actually
    paid. Matches the same rule pdf_service.create_invoice_pdf already uses to
    decide what to print in the "Paid" column."""
    cleaned = (status or "").strip()
    return bool(cleaned) and cleaned.lower() != "not paid"


def _is_refund_of_deposit(description: str) -> bool:
    return "refund of deposit" in description.lower()


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

    # Each due date is clamped forward to never precede the previous one: for
    # a booking whose check-in has already passed (or is very close) by the
    # time the quote is issued, check_in-anchored installments would
    # otherwise fall due before the today-anchored first installment.
    dates = [today + timedelta(days=4)]
    dates.append(max(check_in, dates[-1]))
    for i in range(2, n_installments):
        due = _add_months(check_in, i - 1)
        if due > check_out:
            due = check_out
        dates.append(max(due, dates[-1]))
    return dates


def _installment_row(description: str, amount: float) -> dict[str, Any]:
    return {
        "kind": "installment",
        "description": description,
        "status": "not paid",
        "qty": 1.0,
        "amount": round(amount, 2),
        "vat_rate": 0.0,
    }


def _deposit_refund_row(check_out: date, deposit: float) -> dict[str, Any]:
    refund_due = (check_out + timedelta(days=7)).strftime(_DATE_FMT)
    refund_desc = f"Refund of Deposit (Provided No Damages Are Present); due: {refund_due}"
    return {
        "kind": "deposit_refund",
        "description": refund_desc,
        "status": "not paid",
        "qty": 1.0,
        "amount": round(-deposit, 2),
        "vat_rate": 0.0,
    }


def _fresh_plan_rows(
    total_charges: float,
    end_cleaning: float,
    admin_costs: float,
    deposit: float,
    n_installments: int,
    due_strs: list[str],
) -> list[dict[str, Any]]:
    """The original from-scratch schedule (no rows already paid)."""
    payments: list[dict[str, Any]] = []

    if n_installments == 1:
        deposit_text = " + Deposit" if deposit > 0 else ""
        description = f"Installment 1 - Full period + City Tax{deposit_text}; due: {due_strs[0]}"
        payments.append(_installment_row(description, total_charges))
        return payments

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

    return payments


def _remainder_rows(
    remaining: float,
    n_new: int,
    paid_installments: int,
    due_strs: list[str],
) -> list[dict[str, Any]]:
    """New installments covering what's left after already-paid rows, continuing
    the numbering/ordinals from where the paid rows left off. Assumes (as the
    original fresh-plan schedule does) that the first paid installment was the
    "Confirms booking" row, so the rental-period ordinal picks up from there."""
    rental_already_paid = max(paid_installments - 1, 0)
    per_installment = round(remaining / n_new, 2) if n_new else 0.0

    rows: list[dict[str, Any]] = []
    for j in range(1, n_new + 1):
        if j == n_new:
            paid_so_far = round(per_installment * (n_new - 1), 2)
            amount = round(remaining - paid_so_far, 2)
        else:
            amount = per_installment
        ordinal_idx = rental_already_paid + j
        description = (
            f"Installment {paid_installments + j} - {_ordinal(ordinal_idx)} Rental Period + "
            f"city tax; due: {due_strs[j - 1]}"
        )
        rows.append(_installment_row(description, amount))
    return rows


def build_payment_plan(
    charges: list[ChargeLine],
    check_in: date,
    check_out: date,
    installments: int = 1,
    security_deposit: float = 0.0,
    existing_payments: Optional[list[PaymentRow]] = None,
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

    kept = [row for row in (existing_payments or []) if is_paid(row.status)]

    if not kept:
        due_dates = _due_dates(check_in, check_out, n_installments, today)
        due_strs = [d.strftime(_DATE_FMT) for d in due_dates]
        payments = _fresh_plan_rows(total_charges, end_cleaning, admin_costs, deposit, n_installments, due_strs)
        if deposit > 0:
            payments.append(_deposit_refund_row(check_out, deposit))
        return {
            "installments": n_installments,
            "total_charges": total_charges,
            "payments": payments,
            "kept_count": 0,
            "paid_total": 0.0,
            "remaining": round(total_charges, 2),
        }

    # Regenerating over existing paid rows: never touch them, only re-split
    # whatever's left of the new total across new installments (or refund the
    # difference if the new total came out lower than what's already paid).
    paid_total = round(sum(row.line_total for row in kept if not _is_refund_of_deposit(row.description)), 2)
    paid_installments = sum(1 for row in kept if row.amount > 0)
    remaining = round(total_charges - paid_total, 2)
    has_kept_deposit_refund = any(_is_refund_of_deposit(row.description) for row in kept)

    payments: list[dict[str, Any]] = [
        {
            "kind": "kept",
            "description": row.description,
            "status": row.status,
            "qty": row.qty,
            "amount": row.amount,
            "vat_rate": row.vat_rate,
        }
        for row in kept
    ]

    if remaining > _ROUNDING_EPSILON:
        n_new = n_installments - paid_installments
        if n_new <= 0:
            n_new = 1
        due_dates = _due_dates(check_in, check_out, paid_installments + n_new, today)[paid_installments:]
        due_strs = [d.strftime(_DATE_FMT) for d in due_dates]
        payments.extend(_remainder_rows(remaining, n_new, paid_installments, due_strs))
    elif remaining < -_ROUNDING_EPSILON:
        refund_due = (today + timedelta(days=7)).strftime(_DATE_FMT)
        payments.append(
            {
                "kind": "overpayment_refund",
                "description": f"Refund of overpayment; due: {refund_due}",
                "status": "not paid",
                "qty": 1.0,
                "amount": remaining,
                "vat_rate": 0.0,
            }
        )

    if deposit > 0 and not has_kept_deposit_refund:
        payments.append(_deposit_refund_row(check_out, deposit))

    return {
        "installments": n_installments,
        "total_charges": total_charges,
        "payments": payments,
        "kept_count": len(kept),
        "paid_total": paid_total,
        "remaining": remaining,
    }
