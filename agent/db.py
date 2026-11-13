# db.py: where the SQLite file lives, how it is seeded, and the ONLY write path.
#
# Capstone Step 3 (domain data foundation) and Step 8 (zero-code database evolution).
#
# Two kinds of connection exist in this project, on purpose:
#   * read-only  -> connect_ro()             used by every agent tool (Step 4)
#   * read-write -> seed_database() and apply_live_migration()
#                   used by humans only (seed script, Streamlit button).
#                   These functions are NEVER registered as agent tools.
#
# EXAMPLE DATA ONLY. No real customer names, prices or product codes.

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "enterprise.db"
DEFAULT_POLICIES = ROOT / "policies"


def db_path() -> Path:
    """Database location. ENTERPRISE_DB lets tests use a temp copy."""
    return Path(os.environ.get("ENTERPRISE_DB") or DEFAULT_DB).resolve()


def policies_dir() -> Path:
    return Path(os.environ.get("POLICIES_DIR") or DEFAULT_POLICIES).resolve()


def ro_uri(path: Path | None = None) -> str:
    """file:...?mode=ro URI (Lab 6 / Step 4: physical read-only lock)."""
    return (path or db_path()).as_uri() + "?mode=ro"


def connect_ro() -> sqlite3.Connection:
    """Read-only connection. Any write raises sqlite3.OperationalError."""
    ensure_database()
    return sqlite3.connect(ro_uri(), uri=True)


# --------------------------------------------------------------------------
# Seed data (all invented)
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku          TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    category     TEXT NOT NULL,
    uom          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_rules (
    sku                  TEXT PRIMARY KEY REFERENCES products(sku),
    currency             TEXT NOT NULL DEFAULT 'MYR',
    unit_cost            REAL NOT NULL,
    list_price           REAL NOT NULL,
    min_margin_pct       REAL NOT NULL,
    price_floor          REAL NOT NULL,
    volume_break_qty     REAL NOT NULL,
    volume_discount_pct  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stock (
    sku                     TEXT PRIMARY KEY REFERENCES products(sku),
    warehouse               TEXT NOT NULL,
    available_qty           REAL NOT NULL,
    uom                     TEXT NOT NULL,
    lead_time_days_in_stock INTEGER NOT NULL,
    lead_time_days_indent   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    customer_id    TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    tier           TEXT NOT NULL,
    payment_terms  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS past_quotes (
    quote_id       TEXT PRIMARY KEY,
    quote_date     TEXT NOT NULL,
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id),
    sku            TEXT NOT NULL REFERENCES products(sku),
    qty            REAL NOT NULL,
    uom            TEXT NOT NULL,
    unit_price     REAL NOT NULL,
    currency       TEXT NOT NULL DEFAULT 'MYR',
    incoterms      TEXT,
    lead_time_days INTEGER,
    notes          TEXT
);
"""

SEED_TABLES = ("products", "price_rules", "stock", "customers", "past_quotes")

PRODUCTS = [
    ("EXAMPLE-RESIN-001", "EXAMPLE general-purpose resin, 25kg bag", "resin", "KG"),
    ("EXAMPLE-ADDITIVE-002", "EXAMPLE processing additive, 20kg pail", "additive", "KG"),
    ("EXAMPLE-FILM-003", "EXAMPLE packaging film roll", "film", "ROLL"),
]
# sku, currency, unit_cost, list_price, min_margin_pct, price_floor, volume_break_qty, volume_discount_pct
# price_floor = unit_cost * (1 + min_margin_pct / 100), rounded to 2 dp.
PRICE_RULES = [
    ("EXAMPLE-RESIN-001", "MYR", 4.00, 5.00, 10.0, 4.40, 2000, 7.0),
    ("EXAMPLE-ADDITIVE-002", "MYR", 8.50, 11.00, 10.0, 9.35, 1000, 5.0),
    ("EXAMPLE-FILM-003", "MYR", 6.20, 8.00, 10.0, 6.82, 100, 5.0),
]
# sku, warehouse, available_qty, uom, lead_in_stock, lead_indent
STOCK = [
    ("EXAMPLE-RESIN-001", "EXAMPLE_WH_KL", 1000, "KG", 3, 14),
    ("EXAMPLE-ADDITIVE-002", "EXAMPLE_WH_KL", 250, "KG", 5, 21),
    ("EXAMPLE-FILM-003", "EXAMPLE_WH_KL", 40, "ROLL", 7, 28),
]
CUSTOMERS = [
    ("EXC-A", "Example Customer A", "standard", "30 days"),
    ("EXC-B", "Example Customer B", "preferred", "45 days"),
    ("EXC-C", "Example Customer C", "standard", "COD"),
    ("EXC-D", "Example Customer D", "preferred", "60 days"),
]
PAST_QUOTES = [
    ("EXQ-0001", "2026-06-10", "EXC-A", "EXAMPLE-FILM-003", 1, "ROLL", 8.00, "MYR", "EXW", 10, "Example row only"),
    ("EXQ-0002", "2026-07-21", "EXC-C", "EXAMPLE-ADDITIVE-002", 200, "KG", 11.00, "MYR", "FOB", 7, "Example row only"),
    ("EXQ-0003", "2026-08-15", "EXC-A", "EXAMPLE-RESIN-001", 500, "KG", 4.80, "MYR", "EXW", 3, "Example row only"),
    ("EXQ-0004", "2026-09-02", "EXC-B", "EXAMPLE-RESIN-001", 2000, "KG", 4.65, "MYR", "EXW", 5, "Example row only, volume break applied"),
    ("EXQ-0005", "2026-10-01", "EXC-D", "EXAMPLE-RESIN-001", 2, "MT", 4650.00, "MYR", "CIF", 14, "Example row only, price per MT (1 MT = 1000 KG)"),
]


def seed_database(path: Path | None = None, overwrite: bool = False) -> Path:
    """Create enterprise.db with example data. Safe to call twice (idempotent)."""
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and path.exists():
        path.unlink()
    conn = sqlite3.connect(path)  # read-write: seed script only
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT OR IGNORE INTO products VALUES (?,?,?,?)", PRODUCTS)
        conn.executemany("INSERT OR IGNORE INTO price_rules VALUES (?,?,?,?,?,?,?,?)", PRICE_RULES)
        conn.executemany("INSERT OR IGNORE INTO stock VALUES (?,?,?,?,?,?)", STOCK)
        conn.executemany("INSERT OR IGNORE INTO customers VALUES (?,?,?,?)", CUSTOMERS)
        conn.executemany("INSERT OR IGNORE INTO past_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?)", PAST_QUOTES)
        conn.commit()
    finally:
        conn.close()
    return path


def ensure_database() -> Path:
    """Create the database at startup if it is missing (Streamlit Cloud safe)."""
    path = db_path()
    if not path.exists():
        seed_database(path)
    return path


# --------------------------------------------------------------------------
# Step 8: live migration simulator (a human action, NOT an agent tool)
# --------------------------------------------------------------------------
MIGRATION_TABLE = "supplier_lead_times"

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS supplier_lead_times (
    supplier_label   TEXT NOT NULL,
    sku              TEXT NOT NULL REFERENCES products(sku),
    lead_time_days   INTEGER NOT NULL,
    min_order_qty    REAL NOT NULL,
    uom              TEXT NOT NULL,
    PRIMARY KEY (supplier_label, sku)
);
"""
_MIGRATION_ROWS = [
    ("EXAMPLE_SUPPLIER_X", "EXAMPLE-RESIN-001", 14, 1000, "KG"),
    ("EXAMPLE_SUPPLIER_X", "EXAMPLE-ADDITIVE-002", 21, 200, "KG"),
    ("EXAMPLE_SUPPLIER_Y", "EXAMPLE-FILM-003", 28, 10, "ROLL"),
]


def apply_live_migration() -> bool:
    """Add the supplier_lead_times table through a SEPARATE write connection.

    Returns True if the table was created now, False if it already existed.
    The agent has no tool that can reach this function or any write connection.
    """
    path = ensure_database()
    conn = sqlite3.connect(path)  # read-write, human-triggered only
    try:
        existed = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (MIGRATION_TABLE,)
        ).fetchone()
        conn.executescript(_MIGRATION_SQL)
        conn.executemany("INSERT OR IGNORE INTO supplier_lead_times VALUES (?,?,?,?,?)", _MIGRATION_ROWS)
        conn.commit()
    finally:
        conn.close()
    return not existed


def reset_database() -> Path:
    """Rebuild the demo database from the seed (drops the migration table too)."""
    return seed_database(overwrite=True)
