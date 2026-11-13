# mcp_tools.py: the MCP discovery primitives (Capstone Step 4, Lab 6).
#
# Names match the course notebooks (bank_mcp_virtual_analyst_streamlit_participants):
#   mcp_list_tables, mcp_describe_table, mcp_read_query
# plus two document primitives for the policies/ folder:
#   mcp_list_policies, mcp_read_policy
#
# They are plain Python function tools (Lab 2 style), NOT a separate MCP server
# process. See README "Real MCP or function tools?" for why.
#
# Least privilege: there is no write tool. Nothing here can mutate data, and every
# connection is opened with  file:...enterprise.db?mode=ro  (physical read-only lock).
#
# Two-tier safety, data level:
#   1. is_sql_mutation()  parses the SQL with sqlparse and refuses anything that is
#                         not exactly one SELECT statement (AST / token analysis).
#   2. connect_ro()       even if (1) were bypassed, SQLite itself rejects writes.

from __future__ import annotations

import json
import re
import sqlite3

import sqlparse
from sqlparse import tokens as T

from .db import connect_ro, policies_dir

MAX_ROWS = 50

# Keywords that must never appear in a read query. Superset of the Lab 6 / Lab 7 list.
FORBIDDEN = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
    "CREATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA", "VACUUM",
    "RENAME", "UPSERT", "GRANT", "REVOKE", "REINDEX", "ANALYZE",
}
# Function names that read or write outside the database file.
FORBIDDEN_FUNCTIONS = {"LOAD_EXTENSION", "WRITEFILE", "READFILE"}


def is_sql_mutation(sql_query: str) -> bool:
    """Return True if the SQL could change data or schema, or is not a single SELECT.

    AST / token analysis with sqlparse (Lab 6 pattern), hardened:
      * more than one statement (stacked queries)          -> True
      * statement type is not SELECT (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE,
        CREATE, REPLACE, ATTACH, PRAGMA, ...)              -> True
      * a CTE that ends in INSERT/UPDATE/DELETE            -> True (type is not SELECT)
      * a forbidden keyword token anywhere in the tree     -> True
    String literals such as WHERE notes = 'drop' are NOT keywords, so they are allowed.
    Empty input is not a mutation (read_query will reject it separately).
    """
    statements = [s for s in sqlparse.parse(sql_query or "") if str(s).strip().strip(";").strip()]
    if not statements:
        return False
    if len(statements) > 1:
        return True
    stmt = statements[0]
    if stmt.get_type() != "SELECT":
        return True
    for token in stmt.flatten():
        word = token.value.upper()
        if token.ttype in T.Keyword or token.ttype in T.Keyword.DDL or token.ttype in T.Keyword.DML:
            if word in FORBIDDEN:
                return True
        if word in FORBIDDEN_FUNCTIONS:
            return True
    return False


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def mcp_list_tables() -> str:
    """MCP tool: discover every table that currently exists in the enterprise database.

    Call this first. Do not assume which tables exist: new tables can appear at any time.
    Returns JSON: {"status": "success", "tables": [...]}.
    """
    try:
        conn = connect_ro()
        try:
            return json.dumps({"status": "success", "tables": _table_names(conn)})
        finally:
            conn.close()
    except Exception as e:  # keep tool errors as data, never crash the agent loop
        return json.dumps({"status": "error", "message": str(e)})


def mcp_describe_table(table_name: str) -> str:
    """MCP tool: show the columns, types, primary keys and foreign keys of one table.

    Args:
        table_name: A table name returned by mcp_list_tables (for example "price_rules").
    Returns JSON with "columns" and "foreign_keys".
    """
    cleaned = (table_name or "").strip().strip("'").strip('"').strip("`")
    try:
        conn = connect_ro()
        try:
            # Allow-list the name against sqlite_master BEFORE building any PRAGMA text.
            if cleaned not in _table_names(conn):
                return json.dumps({"status": "error", "message": f"Table '{cleaned}' not found."})
            quoted = '"' + cleaned.replace('"', '""') + '"'
            cols = [
                {"cid": r[0], "name": r[1], "type": r[2], "notnull": r[3], "pk": r[5]}
                for r in conn.execute(f"PRAGMA table_info({quoted})")
            ]
            fks = [
                {"column": r[3], "references_table": r[2], "references_column": r[4]}
                for r in conn.execute(f"PRAGMA foreign_key_list({quoted})")
            ]
            return json.dumps({"status": "success", "table": cleaned, "columns": cols, "foreign_keys": fks})
        finally:
            conn.close()
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


def mcp_read_query(sql_query: str) -> str:
    """MCP tool: run ONE read-only SQLite SELECT query and return up to 50 rows.

    Only a single SELECT statement is accepted. Anything that could change data
    (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, CREATE, REPLACE, ATTACH, PRAGMA,
    several statements in one call) is refused. Use mcp_list_tables and
    mcp_describe_table first so you query real column names.

    Args:
        sql_query: A valid SQLite SELECT statement.
    """
    if is_sql_mutation(sql_query):
        return json.dumps({
            "status": "blocked",
            "error": "[MCP PROTOCOL ENFORCEMENT] Mutation operations (DROP, DELETE, UPDATE, INSERT, "
                     "ALTER, TRUNCATE, CREATE, REPLACE, ATTACH) and multi-statement input are not "
                     "supported by the read-only database endpoint.",
        })
    if not (sql_query or "").strip():
        return json.dumps({"status": "error", "message": "Empty query."})
    try:
        conn = connect_ro()
        try:
            cur = conn.execute(sql_query.strip().rstrip(";"))
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_ROWS + 1)
            truncated = len(rows) > MAX_ROWS
            return json.dumps({
                "status": "success",
                "columns": columns,
                "rows": [list(r) for r in rows[:MAX_ROWS]],
                "row_count": min(len(rows), MAX_ROWS),
                "truncated": truncated,
            })
        finally:
            conn.close()
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


_POLICY_NAME = re.compile(r"^[A-Za-z0-9_\-]+(\.md)?$")


def _policy_files() -> dict[str, "object"]:
    folder = policies_dir()
    if not folder.exists():
        return {}
    return {p.stem: p for p in sorted(folder.glob("*.md"))}


def mcp_list_policies() -> str:
    """MCP tool: list the policy documents available in the policies/ folder.

    Returns JSON: {"status": "success", "policies": ["compliance_handbook", ...]}.
    """
    return json.dumps({"status": "success", "policies": list(_policy_files())})


def mcp_read_policy(policy_name: str) -> str:
    """MCP tool: read one markdown policy document by name (read-only).

    Args:
        policy_name: A name from mcp_list_policies, with or without ".md"
            (for example "quoting_policy").
    """
    name = (policy_name or "").strip()
    if not _POLICY_NAME.match(name):
        return json.dumps({"status": "error", "message": "Invalid policy name."})
    files = _policy_files()
    path = files.get(name[:-3] if name.endswith(".md") else name)
    if path is None:
        return json.dumps({"status": "error", "message": f"Policy '{name}' not found.",
                           "available": list(files)})
    return json.dumps({"status": "success", "policy": path.stem, "content": path.read_text(encoding="utf-8")})


# The ONLY tools any agent receives. No mutation tool exists to register.
MCP_DB_TOOLS = [mcp_list_tables, mcp_describe_table, mcp_read_query]
MCP_POLICY_TOOLS = [mcp_list_policies, mcp_read_policy]
MCP_TOOLS = MCP_DB_TOOLS + MCP_POLICY_TOOLS


def schema_text() -> str:
    """Plain-text schema for the sidebar inspector (rendered with st.text)."""
    listing = json.loads(mcp_list_tables())
    if listing.get("status") != "success":
        return f"Schema unavailable: {listing.get('message')}"
    out = []
    for table in listing["tables"]:
        info = json.loads(mcp_describe_table(table))
        out.append(f"TABLE {table}")
        for c in info.get("columns", []):
            flags = " PK" if c["pk"] else ""
            out.append(f"  - {c['name']} {c['type']}{flags}")
        for fk in info.get("foreign_keys", []):
            out.append(f"  - FK {fk['column']} -> {fk['references_table']}.{fk['references_column']}")
        out.append("")
    return "\n".join(out).rstrip()
