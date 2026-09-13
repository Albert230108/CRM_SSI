"""
Standard boilerplate texts shown on every generated quotation PDF (company header,
conditions, footer, deposit/misc notes), editable from the Settings page's "PDF texts"
tab via the generic /api/config/pdf-texts endpoint (see config_store.py).

Modeled on admin_costs.py's load/cache pattern. Defaults here mirror the values that
used to be hardcoded in pdf_service.py, so a missing key never breaks PDF generation.
"""

import json
import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
PDF_TEXTS_FILE = DATA_DIR / "pdf_texts.json"

_pdf_texts_cache = None

DEFAULT_TEXTS = {
    "header_title": "Quotation",
    "company_info": (
        "<b>Short-Stay Inn</b><br/>"
        "<font size='7'>Hoedemakerplein 2<br/>"
        "7511 JP Enschede<br/>"
        "+31 (0) 53 820 0 946<br/>"
        "KvK: 62430610<br/>"
        "VAT-ID: NL002480262B34</font>"
    ),
    "total_prices_header": "Total prices (Including Citytax & VAT, excluding deposit):",
    "deposit_refund_note": "(Refunded after check-out if no damages)",
    "conditions": (
        "* Down payment will secure the reservation. "
        "* Extension of rental is based on availability. "
        "* Shortening of rental - minimum of 7 days before the new departure date. "
        "* Cancellation - when announced at least 7 days before arrival date then the deposit will be refunded. "
        "* Check in / out in consultation with the agency. "
        "* Liability - Tenant liable for damage or loss. "
        "* Modifications - to be communicated by email; administration costs €40,- excl. VAT per modification."
    ),
    "footer": (
        "IBAN-number: NL 52 INGB 0007 1966 78 | BIC-number: INGBNL2A | chamber of commerce no. 062430610 "
        "| General conditions filed with the district court of Almelo\n"
        "E-mail: info@ShortStayInn.com | Website: www.ShortStayInn.com | Telephone no.: 0031 (0) 53-820 0946"
    ),
}


def load_pdf_texts(force_reload=False):
    """
    Load the editable PDF standard texts from pdf_texts.json, falling back to
    DEFAULT_TEXTS for any key that is missing or if the file itself is absent.
    """
    global _pdf_texts_cache

    if _pdf_texts_cache is not None and not force_reload:
        return _pdf_texts_cache

    texts = dict(DEFAULT_TEXTS)
    try:
        if PDF_TEXTS_FILE.exists():
            with open(PDF_TEXTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            texts.update(data.get("texts") or {})
    except Exception as e:
        print(f"Error loading pdf_texts.json, using defaults: {e}")

    _pdf_texts_cache = texts
    return _pdf_texts_cache


def bust_cache() -> None:
    global _pdf_texts_cache
    _pdf_texts_cache = None
