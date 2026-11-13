"""Seed script: python seed_db.py [--force]

Creates data/enterprise.db with EXAMPLE data only (Capstone Step 3).
The app also calls ensure_database() at startup, so this is optional on Streamlit Cloud.
"""
import sys

from agent.db import seed_database

if __name__ == "__main__":
    path = seed_database(overwrite="--force" in sys.argv)
    print(f"Seeded {path}")
