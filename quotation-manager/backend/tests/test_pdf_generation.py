from datetime import date

from app.services import pdf_service


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
