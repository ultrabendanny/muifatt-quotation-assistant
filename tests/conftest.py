"""Shared fixtures. Every test works on a TEMP copy of the database, never data/enterprise.db."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    from agent.db import seed_database

    path = tmp_path / "enterprise.db"
    seed_database(path)
    monkeypatch.setenv("ENTERPRISE_DB", str(path))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from agent import guardrails

    monkeypatch.setattr(guardrails, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(guardrails, "DATA_DIR", tmp_path)
    return path
