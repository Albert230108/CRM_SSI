"""
PDF invoice generation, ported from the desktop Quotation Manager
(Python-EmailQuotation-1/src/functions.py). Behavior is unchanged from the
original create_invoice_pdf; the main structural difference is that this
version accepts an explicit output_path (computed by
services.tenant_files.next_quotation_output_path) instead of computing its
own auto-incrementing filename via a glob scan - that responsibility now
lives in tenant_files.py so it can be decided before this function runs.

search_booking_by_number and log_event were not ported: booking search goes
through the CRM proxy instead (see api/booking.py), and this service uses
standard `logging` rather than the original's JSONL-file-on-disk logger.
"""

import logging
import pathlib
import re
from datetime import date, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

ASSETS_DIR = pathlib.Path(__file__).resolve().parent.parent / "assets"
DEFAULT_LOGO_PATH = ASSETS_DIR / "logo.jpg"

# Room ID -> studio/room picture link, ported from functions.py's STUDIO_LINK_MAPPING.
STUDIO_LINK_MAPPING = {
    262377: "https://beds24.com/booking2.php?roomid=262377&layout=2",  # Studio 1
    262375: "https://beds24.com/booking2.php?roomid=262375&layout=2",  # Studio 2
    262379: "https://beds24.com/booking2.php?roomid=262379&layout=2",  # Studio 3
    262376: "https://beds24.com/booking2.php?roomid=262376&layout=2",  # Studio 4
    262380: "https://beds24.com/booking2.php?roomid=262380&layout=2",  # Studio 5
    262378: "https://beds24.com/booking2.php?roomid=262378&layout=2",  # Studio 6
    262576: "https://beds24.com/booking2.php?roomid=262576&layout=2",  # Room 1
    262578: "https://beds24.com/booking2.php?roomid=262578&layout=2",  # Room 2
    262579: "https://beds24.com/booking2.php?roomid=262579&layout=2",  # Room 3
    262580: "https://beds24.com/booking2.php?roomid=262580&layout=2",  # Room 4
    262581: "https://beds24.com/booking2.php?roomid=262581&layout=2",  # Room 5
    286739: "https://beds24.com/booking2.php?roomid=286739&layout=2",  # Duplex Apartment
    276128: "https://beds24.com/booking2.php?roomid=276128&layout=2",  # Two-Bedroom Apartment
    271050: "https://beds24.com/booking2.php?roomid=271050&layout=2",  # House
    389957: "https://beds24.com/booking2.php?roomid=389957&layout=2",  # Ground floor
    271049: "https://beds24.com/booking2.php?roomid=271049&layout=2",  # Groundfloor Apartment
    564867: "https://beds24.com/booking2.php?roomid=564867&layout=2",  # Upper floor
}

ROOM_ID_MAPPING = {
    286739: "Duplex Apartment",
    271049: "Groundfloor Apartment",
    271050: "House",
    262576: "Room 1",
    262578: "Room 2",
    262579: "Room 3",
    262580: "Room 4",
    262581: "Room 5",
    262377: "Studio 1",
    262375: "Studio 2",
    262379: "Studio 3",
    262376: "Studio 4",
    262380: "Studio 5",
    262378: "Studio 6",
    276128: "Two-Bedroom Apartment",
    389957: "Ground floor",
}


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text and escape special characters for ReportLab."""
    clean = re.sub(r'<[^>]+>', '', text)
    return escape(clean)


def create_horizontal_line(page_width: float) -> Table:
    """A Table-based horizontal rule spanning the full page width."""
    line = Table([[""]], colWidths=[page_width], hAlign='LEFT')
    line.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1, colors.black),
    ]))
    return line


def split_booking_by_vat(start_date: date, end_date: date, price_per_night: float | dict) -> list[dict]:
    """
    Split a booking into segments by VAT rate: 9% for nights starting before
    2026, 21% from 2026 onward. price_per_night may be a flat float or a
    dict mapping year (int or str) -> nightly rate.
    """
    lines = []
    current_date = start_date

    while current_date < end_date:
        if current_date.year < 2026:
            vat = 9
            vat_end = min(end_date, date(2026, 1, 1))
        else:
            vat = 21
            vat_end = end_date

        nights_count = (vat_end - current_date).days

        if nights_count > 0:
            if isinstance(price_per_night, dict):
                unit_price = price_per_night.get(current_date.year)
                if unit_price is None:
                    unit_price = price_per_night.get(str(current_date.year))
                if unit_price is None:
                    unit_price = next((v for v in price_per_night.values() if isinstance(v, (int, float))), 0.0)
            else:
                unit_price = price_per_night or 0.0

            lines.append({
                'start': current_date,
                'end': vat_end,
                'vat': vat,
                'price': nights_count * unit_price,
                'nights': nights_count,
                'unit_price': unit_price,
            })

        current_date = vat_end

    return lines


def process_invoice_items(
    invoice_items: list[dict],
    room_name: str | None,
    first_night: str | None,
    leaving_day: str | None,
) -> tuple[list[dict], list[dict]]:
    """Split raw invoice items into charges/payments, substituting placeholders."""
    charges: list[dict] = []
    payments: list[dict] = []

    first_night_date = datetime.strptime(first_night, "%Y-%m-%d") if first_night else None
    leaving_day_date = datetime.strptime(leaving_day, "%Y-%m-%d") if leaving_day else None
    current_date = datetime.now()

    for item in invoice_items:
        description = item.get("description", "N/A")
        description = description.replace("[ROOMNAME1]", room_name or "Unknown Room")
        description = description.replace("[FIRSTNIGHT]", first_night_date.strftime("%d-%b-%y") if first_night_date else "Unknown Date")
        description = description.replace("[LEAVINGDAY]", leaving_day_date.strftime("%d-%b-%y") if leaving_day_date else "Unknown Date")
        description = description.replace("[CURRENTDATE:+5day{%e-%b-%y}]", (current_date + timedelta(days=5)).strftime("%d-%b-%y"))
        description = description.replace("[FIRSTNIGHT:-1month{%e-%b-%y}]", (first_night_date - timedelta(days=30)).strftime("%d-%b-%y") if first_night_date else "Unknown Date")
        if first_night:
            description = description.replace("[FIRSTNIGHT:-4day{%e-%b-%y}]", (datetime.strptime(first_night, "%Y-%m-%d") - timedelta(days=4)).strftime("%d-%b-%y"))

        if item.get("type") == "charge":
            charges.append({
                "description": description,
                "quantity": item.get("qty", 1),
                "amount": round(item.get("amount", 0), 2),
                "line_total": round(item.get("lineTotal", item.get("qty", 1) * item.get("amount", 0)), 2),
                "vat_rate": item.get("vatRate", 0),
            })
        elif item.get("type") == "payment":
            line_total = item.get("lineTotal")
            if line_total is None:
                line_total = item.get("qty", 1) * item.get("amount", 0)
            if "refund of deposit" in description.lower():
                amount_val = -abs(round(item.get("amount", 0), 2))
                line_total_val = -abs(round(line_total, 2))
            else:
                amount_val = abs(round(item.get("amount", 0), 2))
                line_total_val = abs(round(line_total, 2))
            payments.append({
                "description": description,
                "amount": amount_val,
                "line_total": line_total_val,
                "status": item.get("status", "N/A"),
            })

    return charges, payments


def create_invoice_pdf(
    output_path: pathlib.Path,
    tenant_name: str,
    booking_number: str,
    invoice_items: list[dict],
    quotation_date: str,
    quotation_number: int = 1,
    logo_path: pathlib.Path | None = None,
    room_name: str | None = None,
    first_night: str | None = None,
    leaving_day: str | None = None,
    company_info_text: str | None = None,
    security_deposit: float | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    room_id: int | None = None,
    override_price_per_night: float | None = None,
    override_total_nights: int | None = None,
) -> pathlib.Path:
    """
    Generate a PDF invoice at output_path. Behavior ported verbatim from the
    desktop app's functions.create_invoice_pdf, minus the auto-numbering
    (now the caller's responsibility via tenant_files.next_quotation_output_path)
    and the output_folder/glob bookkeeping.
    """
    charges, payments = process_invoice_items(invoice_items, room_name, first_night, leaving_day)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=10,
        bottomMargin=10,
    )
    elements: list[Any] = []
    styles = getSampleStyleSheet()

    resolved_logo_path = logo_path or DEFAULT_LOGO_PATH

    company_info = (
        "<b>Short-Stay Inn</b><br/>"
        "<font size='7'>Hoedemakerplein 2<br/>"
        "7511 JP Enschede<br/>"
        "+31 (0) 53 820 0 946<br/>"
        "KvK: 62430610<br/>"
        "VAT-ID: NL002480262B34</font>"
    )

    custom_color = HexColor("#0099cb")

    logo_height = 60
    logo_width = int(logo_height * 180 / 80)

    try:
        if resolved_logo_path and pathlib.Path(resolved_logo_path).exists():
            logo_element = Image(str(resolved_logo_path), width=logo_width, height=logo_height)
        else:
            logo_element = Paragraph("", styles["Normal"])
    except Exception:
        logger.warning("Could not load logo from %s", resolved_logo_path, exc_info=True)
        logo_element = Paragraph("", styles["Normal"])

    header_data = [[
        Paragraph(f"<b><font color='{custom_color.hexval()}' size='20'>Quotation</font></b>", styles["Title"]),
        logo_element,
        Paragraph(company_info, styles["Normal"]),
    ]]
    page_width = A4[0]

    header_table = Table(
        header_data,
        colWidths=[120, page_width - 320, 120],
        hAlign='LEFT',
    )
    header_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
        ("VALIGN", (2, 0), (2, 0), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (2, 0), (2, 0), 20),
        ("FONTNAME", (2, 0), (2, 0), "Helvetica"),
        ("FONTSIZE", (2, 0), (2, 0), 8),
        ("BOTTOMPADDING", (0, 0), (0, 0), 0),
    ]))
    elements.append(header_table)

    if company_info_text and company_info_text.strip():
        company_info_style = styles["Normal"].clone('CompanyInfoStyle')
        company_info_style.fontSize = 9
        company_info_style.alignment = 0
        company_info_style.leftIndent = 0
        company_info_style.rightIndent = 0

        escaped_company_info = escape(company_info_text.strip())
        formatted_company_info = escaped_company_info.replace('\n', '<br/>')
        company_info_paragraph = Paragraph(formatted_company_info, company_info_style)

        company_info_table = Table([[company_info_paragraph]], colWidths=[120], hAlign='LEFT')
        company_info_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("VALIGN", (0, 0), (0, 0), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("TOPPADDING", (0, 0), (0, 0), 0),
            ("BOTTOMPADDING", (0, 0), (0, 0), 0),
        ]))

        elements.append(Spacer(1, 0))
        elements.append(company_info_table)
        elements.append(Spacer(1, 0))

    page_width = A4[0] - 80
    line = create_horizontal_line(page_width)
    elements.append(line)
    elements.append(Spacer(1, 0))

    booking_info_header = Paragraph(f"<b>Booking Information: {booking_number}</b>", styles["Heading2"])
    booking_info_header.style.fontSize = 10
    elements.append(booking_info_header)
    elements.append(Spacer(1, 0))

    nights: int | str = "N/A"
    if override_total_nights is not None:
        nights = override_total_nights
    elif first_night and leaving_day:
        try:
            first_date = datetime.strptime(first_night, "%Y-%m-%d")
            last_date = datetime.strptime(leaving_day, "%Y-%m-%d")
            nights = (last_date - first_date).days
        except ValueError:
            nights = "N/A"

    tenant_details_left = [
        ["Quotation no:", f"Q{quotation_number:03d}"],
        ["Quotation date:", quotation_date],
        ["Tenant name:", tenant_name],
    ]
    tenant_details_right = [
        ["Check in:", first_night if first_night else "N/A"],
        ["Check out:", leaving_day if leaving_day else "N/A"],
        ["Nights:", str(nights)],
    ]
    company_info_column = ["", "", "", ""]

    combined_details = []
    for i in range(len(tenant_details_left)):
        left_label, left_value = tenant_details_left[i]
        right_label, right_value = tenant_details_right[i] if i < len(tenant_details_right) else ("", "")
        info = company_info_column[i] if i < len(company_info_column) else ""
        combined_details.append([left_label, left_value, right_label, right_value, info])

    tenant_table = Table(combined_details, colWidths=[80, 120, 80, 100, 120], hAlign='LEFT')
    tenant_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(tenant_table)
    elements.append(Spacer(1, 0))

    line = create_horizontal_line(page_width)
    elements.append(line)
    elements.append(Spacer(1, 0))

    charges_header = Paragraph("<b>Charges</b>", styles["Heading2"])
    charges_header.style.fontSize = 10
    elements.append(charges_header)
    elements.append(Spacer(1, 0))

    invoice_data: list[list[Any]] = [["Description", "Quantity", "Price", "Vat %", "Vat", "Total"]]
    total_charges_excl_deposit = 0.0

    description_style = styles["Normal"].clone('DescriptionStyle')
    description_style.fontSize = 8

    for item in charges:
        raw_description = item.get("description", "N/A")
        escaped_description = escape(raw_description)
        description = Paragraph(escaped_description, description_style)
        qty = item.get("quantity", 1)
        price = round(item.get("amount", 0), 2)
        vat_rate = item.get("vat_rate", 0)

        qty_display = str(int(qty)) if qty == int(qty) else str(qty)
        line_total = round(price * qty, 2)
        vat_amount = round(line_total * (vat_rate / 100), 2)

        invoice_data.append([description, qty_display, f"€{price:.2f}", f"{vat_rate}%", f"€{vat_amount:.2f}", f"€{line_total:.2f}"])

        if "deposit" not in raw_description.lower():
            total_charges_excl_deposit += line_total

    total_row_style = styles["Normal"].clone('TotalRowStyle')
    total_row_style.fontSize = 9
    total_row_style.fontName = 'Helvetica-Bold'
    total_row_style.alignment = TA_RIGHT
    total_para = Paragraph(f"Total (excl. deposit)      €{total_charges_excl_deposit:.2f}", total_row_style)
    invoice_data.append(["", "", "", "", total_para, ""])

    page_width = A4[0] - 80
    col_widths = [page_width * 0.4, page_width * 0.12, page_width * 0.12, page_width * 0.12, page_width * 0.12, page_width * 0.12]

    invoice_table = Table(invoice_data, colWidths=col_widths, hAlign='LEFT')
    invoice_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (-1, 0), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("SPAN", (4, -1), (5, -1)),
        ("ALIGN", (4, -1), (5, -1), "RIGHT"),
    ]))
    elements.append(invoice_table)
    elements.append(Spacer(1, 0))

    deposit_amount = security_deposit if security_deposit is not None else 0
    if deposit_amount == 0:
        for item in charges:
            if 'deposit' in item.get('description', '').lower():
                deposit_amount = item.get('line_total', 0)
                break

    if override_price_per_night is not None:
        price_per_night = override_price_per_night
    else:
        price_per_night = round(total_charges_excl_deposit / max(nights if isinstance(nights, int) else 1, 1), 2)

    total_prices_header = Paragraph("<b>Total prices (Including Citytax & VAT, excluding deposit):</b>", styles["Heading2"])
    total_prices_header.style.fontSize = 10
    elements.append(total_prices_header)
    elements.append(Spacer(1, 0))

    small_style = styles["Normal"].clone('SmallTotalsStyle')
    small_style.fontSize = 7
    small_style_right = small_style.clone('SmallTotalsStyleRight')
    small_style_right.alignment = TA_RIGHT
    grand_total_style = styles["Normal"].clone('GrandTotalStyle')
    grand_total_style.fontSize = 7
    grand_total_style_right = grand_total_style.clone('GrandTotalStyleRight')
    grand_total_style_right.alignment = TA_RIGHT

    price_night_para = Paragraph("Price/night:", small_style)
    price_night_value_para = Paragraph(f"€{price_per_night:.2f}", small_style_right)
    price_week_para = Paragraph("Price/week:", small_style)
    price_week_value_para = Paragraph(f"€{round(price_per_night * 7, 2):.2f}", small_style_right)
    price_month_para = Paragraph("Price/month:", small_style)
    price_month_value_para = Paragraph(f"€{round(price_per_night * 30, 2):.2f}", small_style_right)

    total_charges_para = Paragraph("Total charges (excl. deposit):", small_style)
    total_charges_value_para = Paragraph(f"€{total_charges_excl_deposit:.2f}", small_style_right)

    deposit_para = Paragraph("Deposit:", small_style)
    deposit_value_para = Paragraph(f"€{deposit_amount:.2f}", small_style_right)
    refunded_para = Paragraph("<font size='5'>(Refunded after check-out if no damages)</font>", small_style_right)

    correct_grand_total = total_charges_excl_deposit + deposit_amount
    grand_total_para = Paragraph("Grand Total (incl. deposit):", grand_total_style)
    grand_total_value_para = Paragraph(f"€{correct_grand_total:.2f}", grand_total_style_right)

    total_section_data = [
        [price_night_para, price_night_value_para],
        [price_week_para, price_week_value_para],
        [price_month_para, price_month_value_para],
        ["", ""],
        [total_charges_para, total_charges_value_para],
        [deposit_para, deposit_value_para],
        ["", refunded_para],
        ["", ""],
        [grand_total_para, grand_total_value_para],
    ]
    total_table = Table(total_section_data, colWidths=[150, 70], hAlign='LEFT')
    total_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 4), (1, 4), 2),
    ]))
    elements.append(total_table)
    elements.append(Spacer(1, 0))

    line = create_horizontal_line(page_width)
    elements.append(line)
    elements.append(Spacer(1, 0))

    payment_plan_header = Paragraph("<b>Proposed payment schedule:</b>", styles["Heading2"])
    payment_plan_header.style.fontSize = 10
    elements.append(payment_plan_header)
    elements.append(Spacer(1, 0))

    payment_schedule_data: list[list[Any]] = [["Description", "Net", "Paid"]]
    total_paid = 0.0
    total_net = 0.0

    payment_desc_style = styles["Normal"].clone('PaymentDescStyle')
    payment_desc_style.fontSize = 8
    payment_desc_style.alignment = 0
    payment_desc_style.textColor = colors.black

    for payment in payments:
        description = payment.get('description', 'N/A')
        net_amount = payment.get('line_total', 0)

        display_amount = net_amount
        if 'refund of deposit' in description.lower():
            display_amount = -abs(net_amount)

        if 'refund of deposit' not in description.lower():
            total_net += net_amount

        paid_status = payment.get('status', '').strip()
        is_paid = paid_status.lower() != 'not paid' and paid_status != ''

        if is_paid:
            paid_display = paid_status if paid_status else "paid"
            if 'refund of deposit' not in description.lower():
                total_paid += net_amount
        else:
            paid_display = "not paid"

        if '<a href=' in description:
            def escape_link(match: re.Match) -> str:
                url = match.group(1)
                text = match.group(2)
                if url.startswith('bookpay.php?'):
                    url = 'https://beds24.com/' + url
                escaped_text = escape(text)
                return f'<link href="{url}" color="blue"><u>{escaped_text}</u></link>'

            description_for_pdf = re.sub(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>', escape_link, description)
            description_for_pdf = re.sub(r"<a\s+href='([^']+)'[^>]*>([^<]+)</a>", escape_link, description_for_pdf)
            description_para = Paragraph(description_for_pdf, payment_desc_style)
        else:
            stripped_desc = strip_html_tags(description)
            description_para = Paragraph(stripped_desc, payment_desc_style)

        payment_schedule_data.append([description_para, f"€{display_amount:.2f}", paid_display])

    total_due = total_net - total_paid
    total_paid_para = Paragraph(f"<b>Total paid: €{total_paid:.2f}</b>", small_style)
    due_para = Paragraph(f"<b>Due: €{total_due:.2f}</b>", small_style)

    payment_schedule_data.append([total_paid_para, "", ""])
    payment_schedule_data.append([due_para, "", ""])

    payment_schedule_table = Table(payment_schedule_data, colWidths=[340, 80, 80], hAlign='LEFT')
    payment_schedule_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(payment_schedule_table)
    elements.append(Spacer(1, 0))

    studio_info_style = styles["Normal"].clone('StudioInfoStyle')
    studio_info_style.alignment = 1
    studio_info_style.fontSize = 8

    if room_name and room_name.strip():
        dynamic_room_label = room_name.strip()
    elif room_id is not None and room_id in ROOM_ID_MAPPING:
        dynamic_room_label = ROOM_ID_MAPPING[room_id]
    else:
        dynamic_room_label = "Room/Studio"

    info_label = dynamic_room_label.split()[0] if dynamic_room_label else "Studio"
    if info_label.lower() not in ["room", "studio", "apartment", "house"]:
        info_label = dynamic_room_label

    studio_link = STUDIO_LINK_MAPPING.get(room_id) if room_id else None
    if studio_link:
        studio_info_text = f'<b><font color="#0099cb"><a href="{studio_link}">{info_label} pictures &amp; information</a></font></b>'
    else:
        studio_info_text = f'<b><font color="#0099cb">{info_label} pictures &amp; information</font></b>'

    studio_info_paragraph = Paragraph(studio_info_text, studio_info_style)
    elements.append(studio_info_paragraph)
    elements.append(Spacer(1, 0))

    faq_style = styles["Normal"].clone('FAQStyle')
    faq_style.alignment = 1
    faq_style.fontSize = 8

    if first_name and last_name:
        faq_url = f"https://notre.guide/ShortStayInn?clientname={last_name}&clientfirstname={first_name}"
    else:
        faq_url = "https://notre.guide/ShortStayInn/"
    faq_text = f'<b><font color="#0099cb"><a href="{faq_url}">FAQ page of Short-Stay Inn</a></font></b>'

    faq_paragraph = Paragraph(faq_text, faq_style)
    elements.append(faq_paragraph)
    elements.append(Spacer(1, 0))

    line = create_horizontal_line(page_width)
    elements.append(line)
    elements.append(Spacer(1, 0))

    conditions_title_style = styles["Normal"].clone('ConditionsTitleStyle')
    conditions_title_style.alignment = 1
    conditions_title_style.fontSize = 8
    conditions_title = Paragraph("<b>Conditions:</b>", conditions_title_style)
    elements.append(conditions_title)
    elements.append(Spacer(1, 0))

    conditions = (
        "* Down payment will secure the reservation. "
        "* Extension of rental is based on availability. "
        "* Shortening of rental - minimum of 7 days before the new departure date. "
        "* Cancellation - when announced at least 7 days before arrival date then the deposit will be refunded. "
        "* Check in / out in consultation with the agency. "
        "* Liability - Tenant liable for damage or loss. "
        "* Modifications - to be communicated by email; administration costs €40,- excl. VAT per modification."
    )
    smaller_style = styles["Normal"].clone('SmallerStyle')
    smaller_style.fontSize = 7
    smaller_style.alignment = 1
    conditions_paragraph = Paragraph(conditions, smaller_style)
    elements.append(conditions_paragraph)
    elements.append(Spacer(1, 0))

    line = create_horizontal_line(page_width)
    elements.append(line)
    elements.append(Spacer(1, 0))

    footer = (
        "IBAN-number: NL 52 INGB 0007 1966 78 | BIC-number: INGBNL2A | chamber of commerce no. 062430610 "
        "| General conditions filed with the district court of Almelo\n"
        "E-mail: info@ShortStayInn.com | Website: www.ShortStayInn.com | Telephone no.: 0031 (0) 53-820 0946"
    )
    footer_style = styles["Normal"].clone('FooterStyle')
    footer_style.fontSize = 7
    footer_style.alignment = 1
    footer_paragraph = Paragraph(footer, footer_style)
    elements.append(footer_paragraph)

    pdf.build(elements)
    logger.info("Invoice PDF generated at %s", output_path)
    return output_path
