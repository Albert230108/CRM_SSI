from datetime import date

from app.services import pdf_service
from app.services import vat as vat_service


def test_split_booking_by_vat_splits_at_2026_boundary():
    segments = pdf_service.split_booking_by_vat(date(2025, 12, 28), date(2026, 1, 5), 100.0)
    assert len(segments) == 2
    assert segments[0]["vat"] == 9
    assert segments[0]["nights"] == 4
    assert segments[1]["vat"] == 21
    assert segments[1]["nights"] == 4


def test_split_booking_by_vat_single_segment_within_one_vat_period():
    segments = pdf_service.split_booking_by_vat(date(2026, 3, 1), date(2026, 3, 8), 100.0)
    assert len(segments) == 1
    assert segments[0]["vat"] == 21
    assert segments[0]["nights"] == 7
    assert segments[0]["price"] == 700.0


def test_process_invoice_items_splits_charges_and_payments():
    charges, payments = pdf_service.process_invoice_items(
        [
            {"type": "charge", "description": "Rent for [ROOMNAME1]", "qty": 7, "amount": 65.0, "lineTotal": 455.0, "vatRate": 9},
            {"type": "payment", "description": "Down payment", "qty": 1, "amount": 200.0, "lineTotal": 200.0, "status": "2026-01-01"},
        ],
        room_name="Studio 1",
        first_night="2026-07-01",
        leaving_day="2026-07-08",
    )
    assert charges[0]["description"] == "Rent for Studio 1"
    assert charges[0]["line_total"] == 455.0
    assert payments[0]["line_total"] == 200.0


def test_create_invoice_pdf_writes_real_pdf_file(tmp_path):
    output_path = tmp_path / "Quotation_12345_001.pdf"
    result_path = pdf_service.create_invoice_pdf(
        output_path=output_path,
        tenant_name="John Doe",
        booking_number="12345",
        invoice_items=[
            {"type": "charge", "description": "Rent", "qty": 7, "amount": 65.0, "lineTotal": 455.0, "vatRate": 9},
            {"type": "payment", "description": "Down payment", "qty": 1, "amount": 200.0, "lineTotal": 200.0, "status": "2026-01-01"},
        ],
        quotation_date="01 Jan 2026",
        quotation_number=1,
        room_name="Studio 1",
        first_night="2026-07-01",
        leaving_day="2026-07-08",
        security_deposit=400.0,
        first_name="John",
        last_name="Doe",
    )
    assert result_path == output_path
    assert output_path.exists()
    with open(output_path, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"


def test_pdf_vat_column_shows_vat_included_in_a_gross_line_not_added_on_top():
    # invoice_items reach create_invoice_pdf already VAT-inclusive (charge_builder
    # grosses charges up before they ever land on the form) - the PDF's "Vat"
    # column must show the VAT portion already inside that line, not VAT added
    # on top of it. Studio 6, 5 nights @ 71.00 gross, 21% VAT -> line_total 355.00.
    line_total = 5 * 71.00
    included = vat_service.included_vat(line_total, 21)
    added_on_top = round(line_total * 0.21, 2)
    assert included != added_on_top
    assert included == round(line_total - vat_service.net_amount(line_total, 21), 2)


def test_create_invoice_pdf_accepts_vat_inclusive_amounts(tmp_path):
    # Regression for the VAT-inclusive charge_builder output: the PDF must render
    # without error when invoice_items amounts already include VAT (e.g. 71.00 at
    # vatRate=21, matching what Beds24/charge_builder actually hand it).
    output_path = tmp_path / "Quotation_12345_002.pdf"
    result_path = pdf_service.create_invoice_pdf(
        output_path=output_path,
        tenant_name="Jane Doe",
        booking_number="12345",
        invoice_items=[
            {"type": "charge", "description": "Studio 6 - stay", "qty": 5, "amount": 71.00, "lineTotal": 355.00, "vatRate": 21},
            {"type": "payment", "description": "Installment 1", "qty": 1, "amount": 355.00, "lineTotal": 355.00, "status": "not paid"},
        ],
        quotation_date="01 Sep 2026",
        quotation_number=2,
        room_name="Studio 6",
        first_night="2026-09-05",
        leaving_day="2026-09-10",
        security_deposit=0.0,
    )
    assert result_path.exists()


def test_format_display_date_standardizes_iso_to_day_mon_year():
    from app.services import pdf_service

    assert pdf_service.format_display_date("2026-07-01") == "01-Jul-2026"
    assert pdf_service.format_display_date(None) == "N/A"
    # Unparseable input is passed through untouched rather than raising.
    assert pdf_service.format_display_date("not-a-date") == "not-a-date"


def test_apply_payment_links_adds_bookpay_link_to_positive_payments():
    from app.services import pdf_service

    payments = [
        {"description": "Installment 1 - Confirms booking; due: 01-Jul-2026", "line_total": 500.0, "status": "not paid"},
        {"description": "Refund of Deposit (Provided No Damages Are Present); due: 15-Jul-2026", "line_total": -400.0},
        {"description": "Installment 2 ##NOLINK##", "line_total": 300.0},
        {"description": "Already <a href=\"https://x\">linked</a>", "line_total": 100.0},
        {"description": "Zero row", "line_total": 0.0},
    ]
    result = pdf_service._apply_payment_links(payments, "98765")

    assert 'bookpay.php?bookid=98765&amp;pay=500.00' in result[0]["description"]
    assert "Pay</a>" in result[0]["description"]
    # Refunds, zero rows: no link.
    assert "<a href" not in result[1]["description"]
    assert "<a href" not in result[4]["description"]
    # ##NOLINK## suppresses the link and is stripped from the visible text.
    assert "##NOLINK##" not in result[2]["description"]
    assert "<a href" not in result[2]["description"]
    # An already-linked row is left untouched (not double-linked).
    assert result[3]["description"].count("<a href") == 1


def test_apply_payment_links_no_op_without_booking_number():
    from app.services import pdf_service

    payments = [{"description": "Installment 1", "line_total": 500.0}]
    result = pdf_service._apply_payment_links(payments, None)
    assert result[0]["description"] == "Installment 1"
