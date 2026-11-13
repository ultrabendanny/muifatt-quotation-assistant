# quote_pdf.py: in-memory PDF for an approved draft quote (fpdf2).
# Carried over unchanged from the earlier Quotation Assistant (agent/tools.py).
# Streamlit Cloud has no user-visible filesystem, so the bytes go to st.download_button.
# This is NOT an agent tool: no model can call it.

from __future__ import annotations

def _latin1(text) -> str:
    """fpdf2's built-in fonts are Latin-1 only; replace anything else so PDF building never crashes."""
    text = str(text if text is not None else "")
    text = text.translate(str.maketrans({"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'",
                                         "\u201c": '"', "\u201d": '"', "\u2026": "..."}))
    return text.encode("latin-1", "replace").decode("latin-1")


def build_quote_pdf_bytes(quote_draft: dict) -> bytes:
    """Render the draft quote as a one-page PDF, fully in memory (no file written).

    Streamlit Cloud has no user-visible filesystem, so the app hands these bytes to
    st.download_button instead of showing a /tmp path.
    """
    from fpdf import FPDF  # fpdf2 (see requirements.txt)

    draft = quote_draft if isinstance(quote_draft, dict) else {}
    currency = draft.get("currency") or "MYR"

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Draft Quotation", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, "Internal draft - example data only - not sent to any customer",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _latin1(f"Quote ID: {draft.get('quote_id', 'n/a')}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _latin1(f"Currency: {currency}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _latin1(f"Valid for: {draft.get('validity_days', 14)} days"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 9)
    with pdf.table(col_widths=(6, 30, 44, 12, 9, 15, 17, 12), text_align="LEFT") as table:
        header = table.row()
        for h in ("#", "SKU", "Description", "Qty", "UoM", "Unit price", "Line total", "Lead (d)"):
            header.cell(h)
        for line in draft.get("lines") or []:
            if not isinstance(line, dict):
                continue
            row = table.row()
            for v in (
                line.get("line_no"), line.get("sku"), line.get("description"),
                line.get("qty"), line.get("uom"), line.get("unit_price"),
                line.get("line_total"), line.get("lead_time_days"),
            ):
                row.cell(_latin1(v))

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1(f"Subtotal: {currency} {draft.get('subtotal', 'n/a')}"),
             new_x="LMARGIN", new_y="NEXT")

    for title, key in (("Notes", "notes"), ("Warnings", "warnings")):
        items = draft.get(key) or []
        if items:
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            for item in items:
                pdf.multi_cell(0, 5, _latin1(f"- {item}"), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 4, "Approved by a human reviewer in the Quotation Assistant. "
                   "Figures are example only. This document has not been emailed or shared.",
                   new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def format_quote_pdf(quote_draft: dict, approval_status: str) -> dict:
    """Build a PDF of an approved draft quote, in memory.

    Call this only after a human has set approval_status to 'approved'.
    Never emails, shares, or uploads the file. Returns the PDF bytes (for a local
    download button) plus a checksum for the audit log. If approval_status is not
    'approved', refuse.
    Args:
        quote_draft: The JSON draft quote object.
        approval_status: Must be 'approved' or the tool returns an error.
    """
    if approval_status != "approved":
        return {"ok": False, "error": "Refused: quote is not approved. No file written."}
    quote_id = "EXAMPLE-DRAFT"
    if isinstance(quote_draft, dict):
        quote_id = quote_draft.get("quote_id") or quote_id
    try:
        data = build_quote_pdf_bytes(quote_draft)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    import hashlib

    safe_id = "".join(c for c in str(quote_id) if c.isalnum() or c in "-_") or "EXAMPLE-DRAFT"
    return {
        "ok": True,
        "example_only": True,
        "filename": f"{safe_id}.pdf",
        "pdf_bytes": data,
        "sha256": hashlib.sha256(data).hexdigest(),
        "note": "Local download only. Not sent to any customer.",
    }


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
