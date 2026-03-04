"""
PDF Parser for ASC 606 Order Form Extraction
=============================================
Uses pdfplumber to extract text from uploaded PDFs and attempts to
parse structured order form data. Falls back to raw text if parsing fails.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

import pdfplumber

from engine import LineItem, OrderForm, ProductType


# ---------------------------------------------------------------------------
# Product-type keyword mapping (case-insensitive matching)
# ---------------------------------------------------------------------------

_PRODUCT_TYPE_KEYWORDS: dict[str, list[str]] = {
    ProductType.CODER_PREMIUM.value: [
        "coder premium",
        "coder enterprise",
        "coder platform",
        "coder subscription",
    ],
    ProductType.AWB.value: [
        "agent ready workspace",
        "agent-ready workspace",
        "arw",
        "agent workspace",
        "awb",
        "workspace build",
        "agent build",
        "agent workspace build",
    ],
    ProductType.AI_GOVERNANCE.value: [
        "ai governance",
        "governance license",
        "governance add-on",
        "ai governance license",
        "ai gov",
    ],
    ProductType.LICENSE.value: [
        "software license",
        "license fee",
        "perpetual license",
        "term license",
        "subscription license",
        "platform license",
        "enterprise license",
    ],
    ProductType.SUPPORT.value: [
        "support",
        "maintenance",
        "support & maintenance",
        "support and maintenance",
        "premium support",
        "technical support",
        "s&m",
    ],
}


def _classify_product_type(description: str) -> str:
    """Classify a line item description into a ProductType."""
    desc_lower = description.lower()
    
    # Special case: "Coder Premium - Agent Ready Workspaces" is AWB, not coder_premium
    if "agent ready" in desc_lower or "agent-ready" in desc_lower or "arw" in desc_lower:
        return ProductType.AWB.value
    
    for ptype, keywords in _PRODUCT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in desc_lower:
                return ptype
    # Default to coder_premium if "coder" appears anywhere
    if "coder" in desc_lower:
        return ProductType.CODER_PREMIUM.value
    # Final fallback
    return ProductType.LICENSE.value


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y/%m/%d",
]


def _try_parse_date(text: str) -> Optional[str]:
    """Attempt to parse a date string into ISO format. Return None on failure."""
    text = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _find_date_in_text(text: str, label: str) -> Optional[str]:
    """Search for a labelled date in text. Returns ISO string or None."""
    patterns = [
        rf"{label}\s*[:\-]?\s*(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})",
        rf"{label}\s*[:\-]?\s*(\d{{4}}-\d{{2}}-\d{{2}})",
        rf"{label}\s*[:\-]?\s*(\w+ \d{{1,2}},\s*\d{{4}})",
        rf"{label}\s*[:\-]?\s*(\d{{1,2}}-\w{{3}}-\d{{2,4}})",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            parsed = _try_parse_date(match.group(1))
            if parsed:
                return parsed
    return None


# ---------------------------------------------------------------------------
# Money parsing helpers
# ---------------------------------------------------------------------------

def _parse_money(text: str) -> Optional[float]:
    """Extract a monetary value from text like '$1,234.56' or '1234.56'."""
    text = text.strip().replace(",", "").replace("$", "")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _find_money_in_text(text: str, label: str) -> Optional[float]:
    """Find a labelled monetary value in text."""
    patterns = [
        rf"{label}\s*[:\-]?\s*\$?([\d,]+\.?\d*)",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return _parse_money(match.group(1))
    return None


# ---------------------------------------------------------------------------
# Line item extraction
# ---------------------------------------------------------------------------

def _extract_line_items_from_text(text: str) -> list[LineItem]:
    """
    Attempt to parse line items from tabular text.
    Looks for patterns like:
        Description    Qty    Unit Price    Total
        Software License   1   $50,000.00   $50,000.00
    """
    items: list[LineItem] = []

    # Pattern: description, then numbers for qty, unit price, total
    # Flexible pattern to match common table rows
    line_pattern = re.compile(
        r"^(.+?)\s+"
        r"(\d+)\s+"
        r"\$?([\d,]+\.?\d*)\s+"
        r"\$?([\d,]+\.?\d*)\s*$",
        re.MULTILINE,
    )

    for match in line_pattern.finditer(text):
        desc = match.group(1).strip()
        qty_str = match.group(2).strip()
        unit_str = match.group(3).strip()
        total_str = match.group(4).strip()

        # Skip header rows
        if any(
            h in desc.lower()
            for h in ["description", "item", "product", "qty", "quantity"]
        ):
            continue

        qty = int(qty_str)
        unit_price = _parse_money(unit_str)
        total = _parse_money(total_str)

        if unit_price is not None and total is not None:
            product_type = _classify_product_type(desc)
            items.append(
                LineItem(
                    description=desc,
                    quantity=qty,
                    unit_price=unit_price,
                    total=total,
                    product_type=product_type,
                )
            )

    # Fallback: try a simpler two-column pattern (description + total)
    if not items:
        simple_pattern = re.compile(
            r"^(.+?)\s+\$?([\d,]+\.?\d*)\s*$",
            re.MULTILINE,
        )
        for match in simple_pattern.finditer(text):
            desc = match.group(1).strip()
            total_str = match.group(2).strip()

            if any(
                h in desc.lower()
                for h in [
                    "description", "total", "subtotal", "tax", "grand",
                    "page", "date", "customer",
                ]
            ):
                continue

            total = _parse_money(total_str)
            if total is not None and total > 0:
                product_type = _classify_product_type(desc)
                items.append(
                    LineItem(
                        description=desc,
                        quantity=1,
                        unit_price=total,
                        total=total,
                        product_type=product_type,
                    )
                )

    return items


# ---------------------------------------------------------------------------
# Main extraction from text
# ---------------------------------------------------------------------------

def _extract_bill_to_section(text: str) -> str:
    """Extract the Bill To section from the order form text.

    Looks for a 'Bill To' header and captures everything until the next
    major section header (e.g. 'Product', 'Order Details', etc.).
    Handles cases where 'Bill To' has no colon.
    """
    # Try with optional colon / newline
    bill_to_pattern = re.search(
        r"bill\s*to\s*[:\-]?\s*\n(.*?)(?=\n\s*(?:"
        r"ship\s*to|sold\s*to|order\s*(?:details|summary|items)"
        r"|product|line\s*items|description|prepared\s*by"
        r"|authorized|signature|total|quantity|list\s*price"
        r"|_{3,}|\-{3,}|={3,}"
        r")|\'\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if bill_to_pattern:
        return bill_to_pattern.group(1).strip()

    # Broader fallback: grab lines after "Bill To" until a section break
    simple = re.search(
        r"bill\s*to\s*[:\-]?\s*\n(.+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if simple:
        lines = simple.group(1).strip().split("\n")[:15]
        return "\n".join(lines)
    return ""


def _extract_customer_name(text: str) -> str:
    """Extract Account Name from the order form.

    Searches for an explicit 'Account Name:' label. Strips anything
    after 'Prepared By' which may appear on the same line in PDFs.
    """
    patterns = [
        r"(?:account\s*name)\s*[:\-]?\s*(.+)",
        r"(?:customer\s*name|company\s*name)\s*[:\-]?\s*(.+)",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            name = name.split("\n")[0].strip()
            # Remove 'Prepared By...' that may appear on the same line
            name = re.split(r"\s+Prepared\s", name, flags=re.IGNORECASE)[0].strip()
            name = re.sub(r"\s*\d{1,2}/\d{1,2}/\d{2,4}.*", "", name).strip()
            if len(name) > 2:
                return name
    return "Unknown Customer"


def _extract_contact_name(text: str) -> str:
    """Extract contact name from the Bill To section of the order form.

    Handles multi-column PDF extraction where Name may appear without
    a colon, e.g. 'Name Beverley Doyle Address: ...'.
    """
    bill_to = _extract_bill_to_section(text)

    # --- Search within Bill To first ---
    if bill_to:
        bt_patterns = [
            # "Name: Beverley Doyle" (with colon)
            r"(?:contact\s*name|(?:^|\n)\s*name)\s*[:\-]\s*([A-Za-z][A-Za-z .\-']+)",
            # "Name Beverley Doyle Address:" (no colon, multi-column merge)
            # Capture word(s) after 'Name' up to next label like 'Address', 'Email', 'Phone' etc.
            r"(?:^|\n|\s)Name\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*(?:Address|Email|Phone|Fax|$)",
            # Attention/Attn
            r"(?:attention|attn)\.?\s*[:\-]?\s*([A-Za-z][A-Za-z .\-']+)",
        ]
        for pat in bt_patterns:
            match = re.search(pat, bill_to, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip().split("\n")[0].strip()
                # Clean trailing labels/punctuation
                name = re.split(r"\s+(?:Address|Email|Phone|Fax)", name, flags=re.IGNORECASE)[0].strip()
                if len(name) > 2 and not re.match(r'^[\d$]', name):
                    return name

    # --- Fallback: search full text but only near Bill To ---
    full_patterns = [
        r"bill\s*to\s*[:\-]?\s*(?:.*\n)*?\s*name\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
        r"(?:contact\s*name)\s*[:\-]?\s*([A-Za-z][A-Za-z .\-']+)",
        r"(?:attention|attn)\.?\s*[:\-]?\s*([A-Za-z][A-Za-z .\-']+)",
    ]
    for pat in full_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip().split("\n")[0].strip()
            name = re.split(r"\s+(?:Address|Email|Phone|Fax)", name, flags=re.IGNORECASE)[0].strip()
            if len(name) > 2 and not re.match(r'^[\d$]', name):
                return name
    return ""


def _extract_email(text: str) -> str:
    """Extract contact email from the Bill To section of the order form.

    Handles multi-column PDF extraction where the email may be split
    across lines, e.g.:
        : qrt_ap@qube-
        Email: rt.com
    which should reconstruct to qrt_ap@qube-rt.com.
    """
    email_re = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
    bill_to = _extract_bill_to_section(text)

    # --- Search within Bill To first ---
    if bill_to:
        # 1. Try a clean email in the Bill To section
        labelled = re.search(
            rf"(?:e-?mail)\s*[:\-]?\s*({email_re})",
            bill_to, re.IGNORECASE,
        )
        if labelled:
            return labelled.group(1).strip()

        any_bt = re.search(email_re, bill_to)
        if any_bt:
            return any_bt.group(0).strip()

        # 2. Handle split email: look for partial email patterns
        #    e.g. lines containing "@" with a domain fragment on the next line,
        #    or "Email:" label with a domain fragment that completes a prior "@" part
        #    Real example from pdfplumber multi-column extraction:
        #      Line: ": qrt_ap@qube- London Greater"
        #      Line: "Email: rt.com London"
        #    Should reconstruct: qrt_ap@qube-rt.com
        bt_lines = bill_to.split("\n")
        partial_user = None
        for line in bt_lines:
            stripped = line.strip()
            # Look for a fragment containing @ (e.g. "qrt_ap@qube-" anywhere in the line)
            at_match = re.search(r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]*-)", stripped)
            if at_match:
                partial_user = at_match.group(1)  # e.g. "qrt_ap@qube-"
                continue
            # If we have a partial, look for the domain completion on a subsequent line
            if partial_user:
                # e.g. "Email: rt.com London" or just "rt.com"
                domain_match = re.search(
                    r"(?:e-?mail\s*[:\-]?\s*)?([A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,})",
                    stripped, re.IGNORECASE,
                )
                if domain_match:
                    reconstructed = partial_user + domain_match.group(1)
                    if re.match(email_re, reconstructed):
                        return reconstructed
                partial_user = None  # reset if we can't match

    # --- Fallback: search full text but EXCLUDE 'Prepared By' emails ---
    # Find all emails, skip ones near "Prepared By"
    for m in re.finditer(email_re, text):
        # Check if this email is on the same line as "Prepared By"
        start = max(0, m.start() - 100)
        context = text[start:m.start()]
        if re.search(r"prepared\s+by", context, re.IGNORECASE):
            continue
        return m.group(0).strip()

    return ""
    return ""


def _extract_text_field(text: str, label: str) -> str:
    """Extract a generic text field by label."""
    patterns = [
        rf"{label}\s*[:\-]?\s*(.+)",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return match.group(1).strip().split("\n")[0].strip()
    return ""


def _parse_text_to_order(text: str) -> tuple[Optional[OrderForm], list[str]]:
    """
    Parse extracted PDF text into an OrderForm object.
    Returns (OrderForm or None, list of parsing warnings).
    """
    parse_warnings: list[str] = []

    # Customer (Account Name)
    customer_name = _extract_customer_name(text)
    if customer_name == "Unknown Customer":
        parse_warnings.append("Could not identify account name — flagged for manual entry.")

    # Contact name
    contact_name = _extract_contact_name(text)
    if not contact_name:
        parse_warnings.append("Could not identify contact name from order form.")

    # Contact email
    contact_email = _extract_email(text)
    if not contact_email:
        parse_warnings.append("Could not identify contact email from order form.")

    # Dates
    order_date = (
        _find_date_in_text(text, "order date")
        or _find_date_in_text(text, "date")
        or _find_date_in_text(text, "effective date")
        or _find_date_in_text(text, "execution date")
        or _find_date_in_text(text, "signature date")
    )
    if not order_date:
        order_date = date.today().isoformat()
        parse_warnings.append(
            f"Could not parse order date — defaulting to today ({order_date})."
        )

    contract_start = (
        _find_date_in_text(text, "contract start")
        or _find_date_in_text(text, "start date")
        or _find_date_in_text(text, "effective date")
        or _find_date_in_text(text, "commencement")
        or _find_date_in_text(text, "subscription start")
        or _find_date_in_text(text, "term start")
        or _find_date_in_text(text, "service start")
    )
    if not contract_start:
        contract_start = order_date
        parse_warnings.append("Could not parse contract start — defaulting to order date.")

    contract_end = (
        _find_date_in_text(text, "contract end")
        or _find_date_in_text(text, "end date")
        or _find_date_in_text(text, "expiration")
        or _find_date_in_text(text, "termination date")
        or _find_date_in_text(text, "subscription end")
        or _find_date_in_text(text, "term end")
        or _find_date_in_text(text, "service end")
    )
    if not contract_end:
        # Default to 1 year from start
        from datetime import timedelta
        start_d = datetime.strptime(contract_start, "%Y-%m-%d").date()
        end_d = start_d + timedelta(days=365)
        contract_end = end_d.isoformat()
        parse_warnings.append(
            f"Could not parse contract end — defaulting to 1 year from start ({contract_end})."
        )

    # TCV
    tcv = (
        _find_money_in_text(text, "total contract value")
        or _find_money_in_text(text, "total value")
        or _find_money_in_text(text, "grand total")
        or _find_money_in_text(text, "contract total")
        or _find_money_in_text(text, "total amount")
        or _find_money_in_text(text, "total fees")
        or _find_money_in_text(text, "total price")
        or _find_money_in_text(text, "net amount")
        or _find_money_in_text(text, "total due")
        or _find_money_in_text(text, "total")
    )

    # Line items
    line_items = _extract_line_items_from_text(text)
    if not line_items:
        parse_warnings.append(
            "Could not extract line items from PDF — manual entry required."
        )

    # If no TCV found, sum line items
    if tcv is None:
        if line_items:
            tcv = round(sum(li.total for li in line_items), 2)
            parse_warnings.append(
                f"Could not find explicit TCV — calculated from line items: ${tcv:,.2f}."
            )
        else:
            tcv = 0.0
            parse_warnings.append("Could not determine total contract value.")

    # Payment / renewal terms
    payment_terms = _extract_text_field(text, "payment terms")
    if not payment_terms:
        payment_terms = _extract_text_field(text, "payment")
    renewal_terms = _extract_text_field(text, "renewal terms")
    if not renewal_terms:
        renewal_terms = _extract_text_field(text, "renewal")

    try:
        order = OrderForm(
            customer_name=customer_name,
            order_date=order_date,
            contract_start=contract_start,
            contract_end=contract_end,
            total_contract_value=tcv,
            line_items=line_items,
            payment_terms=payment_terms,
            renewal_terms=renewal_terms,
            contact_name=contact_name,
            contact_email=contact_email,
        )
        return order, parse_warnings
    except Exception as exc:
        parse_warnings.append(f"Failed to build OrderForm: {exc}")
        return None, parse_warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_text_from_pdf(file_path: str) -> str:
    """Extract all text from a PDF file using pdfplumber."""
    all_text: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                all_text.append(text)
    return "\n".join(all_text)


def parse_pdf_to_order(file_path: str) -> dict:
    """
    Full pipeline: extract text from PDF → parse into OrderForm.

    Returns a dict with:
      - "success": bool
      - "order": OrderForm (or None)
      - "raw_text": str (always included)
      - "parse_warnings": list[str]
      - "needs_manual_entry": bool
    """
    try:
        raw_text = extract_text_from_pdf(file_path)
    except Exception as exc:
        return {
            "success": False,
            "order": None,
            "raw_text": "",
            "parse_warnings": [f"Failed to extract text from PDF: {exc}"],
            "needs_manual_entry": True,
        }

    if not raw_text.strip():
        return {
            "success": False,
            "order": None,
            "raw_text": "",
            "parse_warnings": [
                "PDF appears to be empty or contains only images/scanned content. "
                "pdfplumber cannot extract text from image-based PDFs. "
                "Please enter deal terms manually."
            ],
            "needs_manual_entry": True,
        }

    order, warnings = _parse_text_to_order(raw_text)

    needs_manual = order is None or not order.line_items

    return {
        "success": order is not None,
        "order": order,
        "raw_text": raw_text,
        "parse_warnings": warnings,
        "needs_manual_entry": needs_manual,
    }
