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


def format_quote_pdf(quote_draft: dict, approval_status: str) -> dict:
    """Build a local PDF preview of an approved draft quote.

    Call this only after a human has set approval_status to 'approved'.
    Never emails, shares, or uploads the file. Returns a local path plus a checksum
    for the audit log. If approval_status is not 'approved', refuse.
    Args:
        quote_draft: The JSON draft quote object.
        approval_status: Must be 'approved' or the tool returns an error.
    """
    if approval_status != "approved":
        return {"ok": False, "error": "Refused: quote is not approved. No file written."}
    quote_id = "EXAMPLE-DRAFT"
    if isinstance(quote_draft, dict):
        quote_id = quote_draft.get("quote_id") or quote_id
    path = f"/tmp/{quote_id}.pdf"
    return {
        "ok": True,
        "example_only": True,
        "path": path,
        "note": "Local preview only. Not sent to any customer. PDF bytes not written in this stub.",
    }


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
