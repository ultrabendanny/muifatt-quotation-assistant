# tools.py — stubs with EXAMPLE data only. Replace internals with RAG / MCP later.
# (Lab 2 notebook: typed tools + docstrings as the contract the model reads)
# (Lab 3 notebook lab3_rag_agent_colab_participants.ipynb: wrap retrieval as a function tool;
#  this stub later points at ChromaDB the same way)
# (Day 2 · Lab 6 tool_filter for check_stock — no Lab 6 Colab found in Drive)

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EXAMPLE_QUOTES_CSV = DATA_DIR / "example_past_quotes.csv"


def _load_example_quotes() -> list[dict]:
    """Load fictional example rows. Never treat these as live customer data."""
    if not EXAMPLE_QUOTES_CSV.exists():
        return []
    with EXAMPLE_QUOTES_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def search_past_quotes(query: str, limit: int = 3) -> dict:
    """Search anonymised past quotations for products similar to the query.

    Use this when you need comparable SKUs or prior quote context.
    Returns example_only matches. Never treat results as a live customer promise.
    Args:
        query: Buyer's product wording or an example SKU (e.g. 'EXAMPLE-RESIN-001').
        limit: Maximum number of rows to return (default 3, max 5).
    """
    limit = max(1, min(int(limit or 3), 5))
    q = (query or "").lower()
    rows = _load_example_quotes()
    scored = []
    for row in rows:
        hay = " ".join(
            [
                row.get("sku", ""),
                row.get("description", ""),
                row.get("buyer_label", ""),
            ]
        ).lower()
        score = 0.5 if q and any(tok in hay for tok in q.split()) else 0.2
        if q and q in hay:
            score = 0.9
        scored.append(
            {
                "sku": row.get("sku", "EXAMPLE-SKU"),
                "description": row.get("description", ""),
                "query_match": query,
                "unit_price_example": _to_float(row.get("unit_price")),
                "currency": row.get("currency", "MYR"),
                "uom": row.get("uom", "KG"),
                "quote_date": row.get("quote_date"),
                "buyer_label": row.get("buyer_label", "EXAMPLE_CUSTOMER"),
                "score": score,
            }
        )
    scored.sort(key=lambda r: r["score"], reverse=True)
    if not scored:
        scored = [
            {
                "sku": "EXAMPLE-RESIN-001",
                "description": "EXAMPLE general-purpose resin, 25kg bag",
                "query_match": query,
                "unit_price_example": 4.80,
                "currency": "MYR",
                "uom": "KG",
                "quote_date": "2026-08-15",
                "buyer_label": "EXAMPLE_CUSTOMER_A",
                "score": 0.82,
            }
        ]
    return {"example_only": True, "matches": scored[:limit]}


def get_price_rule(sku_or_query: str, qty: Optional[float] = None, uom: str = "KG") -> dict:
    """Return list price, minimum margin, and price floor for a SKU or product query.

    Use this before proposing any unit price. Do not recommend a price below price_floor.
    Figures are example_only until connected to the real price list.
    Args:
        sku_or_query: Example SKU or the buyer's product wording.
        qty: Requested quantity, if known, for volume-break rules.
        uom: Unit of measure (KG, MT, PC, ROLL).
    """
    # Example-only list. Not a real price list.
    catalogue = {
        "EXAMPLE-RESIN-001": {"unit_cost": 4.00, "list_price": 5.00},
        "EXAMPLE-ADDITIVE-002": {"unit_cost": 8.50, "list_price": 11.00},
        "EXAMPLE-FILM-003": {"unit_cost": 6.20, "list_price": 8.00},
    }
    key = (sku_or_query or "").strip().upper()
    prices = catalogue.get(key, {"unit_cost": 4.00, "list_price": 5.00})
    unit_cost = prices["unit_cost"]
    list_price = prices["list_price"]
    margin_min = 0.10  # 10%
    price_floor = round(unit_cost * (1 + margin_min), 2)
    return {
        "example_only": True,
        "sku": key if key in catalogue else "EXAMPLE-RESIN-001",
        "query": sku_or_query,
        "qty": qty,
        "uom": uom or "KG",
        "currency": "MYR",
        "unit_cost": unit_cost,
        "list_price": list_price,
        "margin_min": margin_min,
        "price_floor": price_floor,
        "volume_note": "Example only — no real volume break applied",
    }


def check_stock(sku: str, qty: Optional[float] = None, uom: str = "KG") -> dict:
    """Check example warehouse availability and typical lead time for a SKU.

    Use this to warn if a requested qty may need indent or a longer lead time.
    This tool must not reserve, allocate, or purchase stock.
    When MCP is connected, allowlist only this tool (tool_filter).
    Args:
        sku: Example SKU such as 'EXAMPLE-RESIN-001'.
        qty: Requested quantity, if known.
        uom: Unit of measure.
    """
    available = 1000.0
    requested = _to_float(qty)
    status = "in_stock" if (requested is None or requested <= available) else "limited"
    return {
        "example_only": True,
        "sku": sku or "EXAMPLE-RESIN-001",
        "requested_qty": requested,
        "available_qty": available,
        "uom": uom or "KG",
        "status": status,
        "lead_time_days": 3 if status == "in_stock" else 14,
        "warehouse": "EXAMPLE_WH_KL",
    }


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
