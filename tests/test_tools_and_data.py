import json
import re
import sqlite3
from pathlib import Path

from agent import db
from agent.mcp_tools import MCP_TOOLS, mcp_list_policies, mcp_list_tables, mcp_read_policy, mcp_read_query

ROOT = Path(__file__).resolve().parents[1]


def test_seed_is_idempotent_and_has_expected_data(temp_db):
    db.seed_database(temp_db)
    db.seed_database(temp_db)
    out = json.loads(mcp_read_query("SELECT available_qty, uom FROM stock WHERE sku='EXAMPLE-RESIN-001'"))
    assert out["rows"] == [[1000.0, "KG"]]
    assert json.loads(mcp_list_tables())["tables"] == ["customers", "past_quotes", "price_rules", "products", "stock"]
    names = json.loads(mcp_read_query("SELECT name FROM customers"))["rows"]
    assert all(n[0].startswith("Example Customer") for n in names)


def test_database_is_created_when_missing(temp_db):
    temp_db.unlink()
    assert json.loads(mcp_list_tables())["status"] == "success"
    assert temp_db.exists()


def test_policies_readable_and_name_checked():
    assert json.loads(mcp_list_policies())["policies"] == ["compliance_handbook", "quoting_policy", "stock_and_lead_time"]
    ok = json.loads(mcp_read_policy("quoting_policy.md"))
    assert ok["status"] == "success" and "price floor" in ok["content"].lower()
    assert json.loads(mcp_read_policy("../app.py"))["status"] == "error"
    assert json.loads(mcp_read_policy("nope"))["status"] == "error"


def test_no_mutation_tool_is_registered():
    names = {f.__name__ for f in MCP_TOOLS}
    assert names == {"mcp_list_tables", "mcp_describe_table", "mcp_read_query", "mcp_list_policies", "mcp_read_policy"}


def test_live_migration_adds_table_through_separate_write_connection(temp_db):
    assert "supplier_lead_times" not in json.loads(mcp_list_tables())["tables"]
    assert db.apply_live_migration() is True
    assert "supplier_lead_times" in json.loads(mcp_list_tables())["tables"]
    assert db.apply_live_migration() is False  # idempotent
    rows = json.loads(mcp_read_query("SELECT count(*) FROM supplier_lead_times"))["rows"]
    assert rows == [[3]]


def test_repo_has_no_secrets_or_real_emails():
    """Public repo check: no API-key shapes, no non-example email addresses."""
    key = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
    email = re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    hits = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or {".git", "venv", "__pycache__", ".pytest_cache"} & set(p.parts):
            continue
        if p.suffix in {".py", ".md", ".json", ".txt", ".toml", ".example", ""}:
            text = p.read_text(encoding="utf-8", errors="ignore")
            if key.search(text) or email.search(text):
                hits.append(str(p.relative_to(ROOT)))
    assert hits == []
