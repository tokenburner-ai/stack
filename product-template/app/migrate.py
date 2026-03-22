"""SQL migration runner — executes numbered .sql files in order."""

import os
import glob
from db import query, execute

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")
_migrated = False


def run_migrations():
    """Run all pending migrations. Safe to call multiple times."""
    global _migrated
    if _migrated:
        return
    _migrated = True

    # Ensure tracking table exists
    execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    applied = {r["version"] for r in query("SELECT version FROM schema_migrations")}

    migration_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    for path in migration_files:
        filename = os.path.basename(path)
        version = int(filename.split("_")[0])
        if version in applied:
            continue

        print(f"Applying migration {filename}...")
        with open(path) as f:
            sql = f.read()
        execute(sql)
        execute(
            "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
            (version, filename),
        )
        print(f"  Applied {filename}")
