# stub.py: offline "stub mode", used when there is no GOOGLE_API_KEY or the live call fails.
#
# This is NOT a language model. It is a small rule-based engine that:
#   * applies the same tier-1 rules (injection block, PII redaction) as the callback,
#   * answers ONLY through the same mcp_* tools the agents use (so the data guardrail,
#     the read-only connection and the policy reader are exercised for real),
#   * is always labelled "STUB" in the UI and in eval_report.md.
# Its answers are deterministic, so eval.py can run in CI or without a key.

from __future__ import annotations

import json
import re

from .db import SEED_TABLES
from .guardrails import BLOCK_MESSAGE, screen_text
from .mcp_tools import (
    is_sql_mutation,
    mcp_describe_table,
    mcp_list_policies,
    mcp_list_tables,
    mcp_read_policy,
    mcp_read_query,
)

SKU_RE = re.compile(r"EXAMPLE-[A-Z]+-\d{3}", re.I)
KEYWORD_SKU = {"resin": "EXAMPLE-RESIN-001", "additive": "EXAMPLE-ADDITIVE-002", "film": "EXAMPLE-FILM-003"}
QTY_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(kg|mt|rolls?)\b", re.I)
TARGET_RE = re.compile(
    r"(?:at|@|for)\s*(?:myr|rm)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:myr|rm)\b", re.I
)
MUTATION_RE = re.compile(
    r"\b(drop\s+table|delete\s+from|truncate\s+table|alter\s+table|insert\s+into|"
    r"update\s+\w+\s+set|create\s+table|replace\s+into|attach\s+database)\b[^\n]*",
    re.I,
)
POLICY_WORDS = ("policy", "policies", "rule", "margin", "floor", "valid", "validity", "discount",
                "compliance", "pdpa", "privacy", "approval", "indent", "volume break", "handbook")
TABLE_WORDS = ("table", "schema", "column", "database", "what data")


def _rows(sql: str) -> list[dict]:
    out = json.loads(mcp_read_query(sql))
    if out.get("status") != "success":
        return []
    cols = out["columns"]
    return [dict(zip(cols, r)) for r in out["rows"]]


def _money(x: float) -> str:
    return f"{x:,.2f}"


def _parse_lines(text: str) -> list[dict]:
    """Very small enquiry parser: segments split on , ; newline and ' and '."""
    lines = []
    for seg in re.split(r"[,;\n]|\s+and\s+", text):
        qty_m = QTY_RE.search(seg)
        sku_m = SKU_RE.search(seg)
        sku = sku_m.group(0).upper() if sku_m else None
        if not sku:
            for word, s in KEYWORD_SKU.items():
                if word in seg.lower():
                    sku = s
                    break
        if not sku:
            continue
        qty = float(qty_m.group(1).replace(",", "")) if qty_m else None
        uom = qty_m.group(2).upper().rstrip("S") if qty_m else None
        target_m = TARGET_RE.search(seg)
        target = float(next(g for g in target_m.groups() if g)) if target_m else None
        lines.append({"line_no": len(lines) + 1, "sku": sku, "qty": qty, "uom": uom, "target_price": target})
    return lines


def _facts(skus: list[str]) -> dict[str, dict]:
    """Price rule + stock + product row per SKU, read through mcp_read_query."""
    safe = [s for s in dict.fromkeys(skus) if SKU_RE.fullmatch(s)]
    if not safe:
        return {}
    in_list = ",".join(f"'{s}'" for s in safe)
    rows = _rows(
        "SELECT p.sku, p.description, p.uom AS base_uom, r.list_price, r.price_floor, "
        "r.volume_break_qty, r.volume_discount_pct, s.available_qty, s.uom AS stock_uom, "
        "s.lead_time_days_in_stock AS lead_in, s.lead_time_days_indent AS lead_indent "
        "FROM products p JOIN price_rules r ON r.sku = p.sku JOIN stock s ON s.sku = p.sku "
        f"WHERE p.sku IN ({in_list})"
    )
    return {r["sku"]: r for r in rows}


def _price_line(line: dict, f: dict) -> dict:
    """Apply quoting_policy.md and stock_and_lead_time.md to one line."""
    qty, uom = line["qty"], line["uom"] or f["base_uom"]
    kg_factor = 1000.0 if uom == "MT" else 1.0
    per_unit = f["list_price"]
    source = "price_rule"
    if qty is not None and qty * kg_factor >= f["volume_break_qty"]:
        per_unit = round(f["list_price"] * (1 - f["volume_discount_pct"] / 100), 2)
        source = "volume_break"
    per_unit = max(per_unit, f["price_floor"])
    unit_price = round(per_unit * kg_factor, 2)
    out = {
        "line_no": line["line_no"], "sku": line["sku"], "description": f["description"],
        "qty": qty, "uom": uom, "unit_price": unit_price,
        "line_total": round(unit_price * qty, 2) if qty is not None else None,
        "price_floor": round(f["price_floor"] * kg_factor, 2),
        "available_qty": f["available_qty"], "stock_uom": f["stock_uom"],
        "lead_time_days": f["lead_in"], "source": source, "warnings": [],
    }
    if qty is not None:
        qty_in_stock_uom = qty * kg_factor
        if qty_in_stock_uom > f["available_qty"]:
            short = qty_in_stock_uom - f["available_qty"]
            out["shortfall_qty"] = short
            out["lead_time_days"] = f["lead_indent"]
            out["warnings"].append(
                f"{line['sku']}: only {f['available_qty']:,.0f} {f['stock_uom']} in stock "
                f"({f['lead_in']} days); shortfall {short:,.0f} {f['stock_uom']} is indent "
                f"({f['lead_indent']} days)."
            )
    target = line.get("target_price")
    if target is not None and target < out["price_floor"] / kg_factor:
        out["warnings"].append(
            f"{line['sku']}: requested price MYR {_money(target)} is below the price floor "
            f"MYR {_money(f['price_floor'])}; cannot quote it. Offering MYR {_money(per_unit)}."
        )
        out["below_floor_request"] = True
    return out


def stub_quote(raw_enquiry: str) -> dict:
    """Deterministic draft quote in the same shape the live pipeline produces."""
    text, blocked = screen_text(raw_enquiry or "")
    parsed = _parse_lines(text)
    facts = _facts([line["sku"] for line in parsed])
    lines, warnings = [], []
    for line in parsed:
        f = facts.get(line["sku"])
        if f is None or line["qty"] is None:
            warnings.append(f"{line['sku']}: missing data or quantity; needs a human.")
            continue
        priced = _price_line(line, f)
        warnings.extend(priced.pop("warnings"))
        lines.append(priced)
    subtotal = round(sum(l["line_total"] or 0 for l in lines), 2)
    return {
        "enquiry": {"buyer_label": "EXAMPLE_CUSTOMER", "currency": "MYR",
                    "lines": [{k: v for k, v in l.items() if k in ("line_no", "sku", "qty", "uom", "target_price")}
                              for l in parsed],
                    "parse_warnings": ["STUB: rule-based parse, no language model was used"]},
        "quote_draft": {"quote_id": "DRAFT-EXAMPLE-STUB", "example_only": True, "currency": "MYR",
                        "validity_days": 14, "lines": lines, "subtotal": subtotal,
                        "notes": ["STUB output computed from the example database"], "warnings": warnings},
        "review": {"score": 4 if lines and not warnings else 3, "pass": bool(lines),
                   "issues": ["STUB reviewer: rule-based, not an LLM judgement"] + warnings},
        "approval_status": "pending",
    }


def _quote_answer(text: str) -> tuple[str, list[str]]:
    parsed = _parse_lines(text)
    if not parsed:
        return "", []
    facts = _facts([l["sku"] for l in parsed])
    parts, subtotal, tools = [], 0.0, ["mcp_read_query"]
    for line in parsed:
        f = facts.get(line["sku"])
        if f is None:
            parts.append(f"- {line['sku']}: not found in the database.")
            continue
        if line["qty"] is None:
            parts.append(
                f"- {line['sku']}: list price MYR {_money(f['list_price'])} per {f['base_uom']} "
                f"(price floor MYR {_money(f['price_floor'])}); {f['available_qty']:,.0f} {f['stock_uom']} "
                f"in stock, lead time {f['lead_in']} days. Quantity not given, no total."
            )
            continue
        p = _price_line(line, f)
        subtotal += p["line_total"] or 0
        parts.append(
            f"- {p['sku']}: {p['qty']:,.0f} {p['uom']} at MYR {_money(p['unit_price'])} per {p['uom']} "
            f"= MYR {_money(p['line_total'])} (price floor MYR {_money(p['price_floor'])}). "
            f"Stock {p['available_qty']:,.0f} {p['stock_uom']}, lead time {p['lead_time_days']} days."
        )
        parts.extend(f"  Note: {w}" for w in p["warnings"])
    if subtotal:
        parts.append(f"Subtotal MYR {_money(subtotal)}. Valid 14 days. Draft only: a human must approve it.")
    return "\n".join(parts), tools


def _policy_answer(question: str) -> tuple[str, list[str]]:
    names = json.loads(mcp_list_policies())["policies"]
    q = question.lower()
    tokens = {w for w in re.findall(r"[a-z]{4,}", q)} - {"what", "that", "this", "with", "does", "have", "about", "tell"}
    scored, tools = [], ["mcp_list_policies", "mcp_read_policy"]
    for name in names:
        doc = json.loads(mcp_read_policy(name))
        for i, line in enumerate(doc.get("content", "").splitlines()):
            if line.startswith("- ") or line.startswith("  - "):
                hits = sum(1 for t in tokens if t in line.lower())
                if hits:
                    scored.append((hits, name, i, line.strip()))
    if not scored:
        return "No matching policy text found. Available policies: " + ", ".join(names), tools
    top = sorted(scored, key=lambda x: (-x[0], x[1], x[2]))[:8]
    out = []
    for name in dict.fromkeys(n for _, n, _, _ in top):
        lines = [l for _, n, i, l in sorted(top, key=lambda x: (x[1], x[2])) if n == name]
        out.append(f"From {name}:\n" + "\n".join(lines))
    return "\n".join(out), tools


def _discover_answer(question: str) -> tuple[str, list[str]]:
    """Zero-code discovery: match the question to ANY table name found at run time.

    This is what makes the live-migration demo work in stub mode: the code never names
    supplier_lead_times, it only compares words in the question with mcp_list_tables.
    """
    tables = json.loads(mcp_list_tables())["tables"]
    tokens = {w.rstrip("s") for w in re.findall(r"[a-z]+", question.lower())}
    tools = ["mcp_list_tables"]
    for t in tables:
        if t in SEED_TABLES:
            continue  # only look for tables the stub was not written for
        parts = {w.rstrip("s") for w in t.split("_")}
        if len(parts) >= 2 and len(parts & tokens) >= 2:
            cols = [c["name"] for c in json.loads(mcp_describe_table(t)).get("columns", [])]
            sku_m = SKU_RE.search(question)
            where = f" WHERE sku = '{sku_m.group(0).upper()}'" if sku_m and "sku" in cols else ""
            res = json.loads(mcp_read_query(f"SELECT * FROM {t}{where} LIMIT 10"))
            tools += ["mcp_describe_table", "mcp_read_query"]
            if res.get("status") != "success":
                return f"Query on {t} failed: {res.get('message') or res.get('error')}", tools
            rows = "\n".join("- " + ", ".join(f"{c}={v}" for c, v in zip(res["columns"], r)) for r in res["rows"])
            return f"Found table '{t}' via mcp_list_tables (columns: {', '.join(cols)}):\n{rows or '(no rows)'}", tools
    if "supplier" in question.lower():
        return ("There is no supplier table in the database right now. "
                f"mcp_list_tables returned: {', '.join(tables)}."), tools
    return "", tools


def stub_answer(question: str) -> dict:
    """Rule-based analyst reply. Always starts with a STUB label."""
    text, blocked = screen_text(question or "")
    label = "[STUB mode, rule-based, no language model] "
    if blocked:
        return {"answer": BLOCK_MESSAGE, "blocked": True, "tools": []}

    tools: list[str] = []
    sections: list[str] = []
    m = MUTATION_RE.search(text)
    if m:
        sql = m.group(0).split(";")[0].strip()
        res = json.loads(mcp_read_query(sql))
        tools.append("mcp_read_query")
        sections.append(
            "I can't do that: the database is read-only. "
            f"The statement was blocked by the data-level guardrail (status: {res.get('status')}, "
            f"is_sql_mutation={is_sql_mutation(sql)}). No tables or rows were changed."
        )
    q = text.lower()
    if not m:
        discovered, d_tools = _discover_answer(text)
        if discovered:
            return {"answer": label + discovered, "blocked": False, "tools": d_tools}
    quote_text, quote_tools = _quote_answer(text)
    no_quote = not quote_text
    if quote_text:
        sections.append(("Draft figures from the database:\n" if not m else "Here is what I can do:\n") + quote_text)
        tools += quote_tools
    if not m and no_quote and any(w in q for w in TABLE_WORDS):
        tables = json.loads(mcp_list_tables())["tables"]
        detail = []
        for t in tables:
            cols = [c["name"] for c in json.loads(mcp_describe_table(t)).get("columns", [])]
            detail.append(f"- {t}: {', '.join(cols)}")
        sections.append("Tables found by mcp_list_tables:\n" + "\n".join(detail))
        tools += ["mcp_list_tables", "mcp_describe_table"]
    elif not m and no_quote and any(w in q for w in POLICY_WORDS):
        body, t = _policy_answer(text)
        sections.append(body)
        tools += t
    elif not sections:
        sections.append("I can answer price, stock, policy and schema questions from the example database. "
                        "Try: 'Quote 500 KG of EXAMPLE-RESIN-001'.")
    return {"answer": label + "\n".join(sections), "blocked": False, "tools": tools}
