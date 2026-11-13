import json
import sqlite3

import pytest

from agent.db import connect_ro, ro_uri
from agent.mcp_tools import is_sql_mutation, mcp_describe_table, mcp_list_tables, mcp_read_query

BLOCKED = [
    "DROP TABLE price_rules",
    "drop table price_rules;",
    "DELETE FROM stock",
    "UPDATE stock SET available_qty = 0",
    "INSERT INTO products VALUES ('X','y','z','KG')",
    "ALTER TABLE stock ADD COLUMN x TEXT",
    "TRUNCATE TABLE stock",
    "CREATE TABLE evil (a int)",
    "REPLACE INTO stock VALUES ('a','b',1,'KG',1,1)",
    "ATTACH DATABASE 'other.db' AS other",
    "PRAGMA writable_schema = 1",
    "SELECT 1; DROP TABLE stock",
    "select * from stock; select * from products",
    "/* harmless */ DROP TABLE stock",
    "-- note\nDELETE FROM stock",
    "WITH x AS (SELECT 1) INSERT INTO stock SELECT * FROM x",
    "SELECT load_extension('x')",
    "VACUUM",
]
ALLOWED = [
    "SELECT * FROM stock",
    "select sku, list_price from price_rules where sku = 'EXAMPLE-RESIN-001';",
    "SELECT * FROM past_quotes WHERE notes = 'drop'",
    "WITH t AS (SELECT sku FROM stock) SELECT * FROM t",
    "SELECT p.sku, s.available_qty FROM products p JOIN stock s ON s.sku = p.sku\nWHERE s.available_qty > 100 ORDER BY 2 DESC",
    "SELECT count(*) FROM customers",
]


@pytest.mark.parametrize("sql", BLOCKED)
def test_mutation_blocked(sql):
    assert is_sql_mutation(sql) is True
    assert json.loads(mcp_read_query(sql))["status"] == "blocked"


@pytest.mark.parametrize("sql", ALLOWED)
def test_select_allowed(sql):
    assert is_sql_mutation(sql) is False
    assert json.loads(mcp_read_query(sql))["status"] == "success"


def test_blocked_statement_changed_nothing():
    mcp_read_query("DROP TABLE price_rules")
    assert "price_rules" in json.loads(mcp_list_tables())["tables"]


def test_readonly_connection_rejects_writes():
    assert "mode=ro" in ro_uri()
    conn = connect_ro()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO products VALUES ('X','y','z','KG')")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DROP TABLE stock")
    conn.close()


def test_describe_table_rejects_injection_and_unknown():
    assert json.loads(mcp_describe_table("price_rules"))["status"] == "success"
    assert json.loads(mcp_describe_table("stock); DROP TABLE stock; --"))["status"] == "error"
    assert json.loads(mcp_describe_table("nope"))["status"] == "error"
    assert "stock" in json.loads(mcp_list_tables())["tables"]
