"""Database connection — Postgres or SQLite-on-S3 (dev mode).

Mode selection (checked in order):
  1. DATABASE_URL set         → Postgres via psycopg2 (production)
  2. S3_DB_BUCKET set         → SQLite file stored in S3 (zero-cost dev)
  3. SQLITE_DB_PATH set       → SQLite local file (offline dev)
  4. fallback                 → Postgres localhost default

SQLite-on-S3 mode:
  - Downloads a .sqlite file from S3 on first request
  - All queries run against local SQLite
  - Writes upload the modified file back to S3
  - Single writer only — not for production
  - Ideal for building APIs and schemas at zero cost
"""

import os
import json
import sqlite3
import threading
import re

# ──────────────────────────────────────────────
# Mode detection
# ──────────────────────────────────────────────
_MODE = None  # "postgres" or "sqlite"
_pool = None  # psycopg2 pool (postgres mode)
_sqlite_conn = None  # sqlite3 connection (sqlite mode)
_sqlite_lock = threading.Lock()
_s3_bucket = None
_s3_key = None
_dirty = False  # tracks if sqlite has unsaved writes


def _detect_mode():
    global _MODE, _s3_bucket, _s3_key
    if _MODE is not None:
        return _MODE

    if os.environ.get("DATABASE_URL") or os.environ.get("DB_SECRET_JSON"):
        _MODE = "postgres"
    elif os.environ.get("S3_DB_BUCKET"):
        _MODE = "sqlite"
        _s3_bucket = os.environ["S3_DB_BUCKET"]
        _s3_key = os.environ.get("S3_DB_KEY", "dev.sqlite")
    elif os.environ.get("SQLITE_DB_PATH"):
        _MODE = "sqlite"
    else:
        _MODE = "postgres"

    return _MODE


# ──────────────────────────────────────────────
# Postgres backend
# ──────────────────────────────────────────────
def _get_pool():
    global _pool
    if _pool is None:
        import psycopg2
        from psycopg2 import pool as pg_pool

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            secret_json = os.environ.get("DB_SECRET_JSON")
            if secret_json:
                s = json.loads(secret_json)
                database_url = (
                    f"postgresql://{s['username']}:{s['password']}"
                    f"@{s['host']}:{s.get('port', 5432)}"
                    f"/{s.get('dbname', 'tokenburner')}"
                )
            else:
                database_url = "postgresql://tokenburner:tokenburner@localhost:5432/tokenburner"
        _pool = pg_pool.ThreadedConnectionPool(1, 10, database_url)
    return _pool


# ──────────────────────────────────────────────
# SQLite backend
# ──────────────────────────────────────────────
_PG_TO_SQLITE = [
    # Type mappings
    (r'\bSERIAL\b', 'INTEGER'),
    (r'\bBIGSERIAL\b', 'INTEGER'),
    (r'\bTIMESTAMPTZ\b', 'TEXT'),
    (r'\bTIMESTAMP\b', 'TEXT'),
    (r'\bJSONB\b', 'JSON'),
    (r'\bBOOLEAN\b', 'INTEGER'),
    (r'\bSMALLINT\b', 'INTEGER'),
    (r'\bBIGINT\b', 'INTEGER'),
    # Function mappings (parens needed for DEFAULT context in SQLite)
    (r'\bnow\(\)', "(datetime('now'))"),
    (r'\bCURRENT_TIMESTAMP\b', "(datetime('now'))"),
    (r'\bTRUE\b', '1'),
    (r'\bFALSE\b', '0'),
]

# Patterns to strip (Postgres-specific clauses SQLite doesn't support)
_PG_STRIP = [
    r'\bIF NOT EXISTS\b',  # SQLite supports this, keep it
]
_PG_REMOVE = [
    r'\bDEFAULT\s+gen_random_uuid\(\)',
    r'\bON\s+CONFLICT\s+DO\s+NOTHING\b',  # keep for INSERT, but may need adjustment
]


def _translate_sql(sql):
    """Best-effort Postgres → SQLite SQL translation."""
    translated = sql
    for pattern, replacement in _PG_TO_SQLITE:
        translated = re.sub(pattern, replacement, translated, flags=re.IGNORECASE)
    return translated


def _translate_params(sql, params):
    """Convert psycopg2 %s params to sqlite3 ? params."""
    if params is None:
        return sql, None
    # Replace %s with ? for positional params
    converted = sql.replace('%s', '?')
    return converted, params


def _get_sqlite():
    """Get or create the SQLite connection."""
    global _sqlite_conn
    if _sqlite_conn is not None:
        return _sqlite_conn

    db_path = os.environ.get("SQLITE_DB_PATH")

    if _s3_bucket:
        # Download from S3
        import tempfile
        # Flatten the S3 key to a safe filename
        safe_name = _s3_key.replace("/", "_").replace("\\", "_")
        db_path = os.path.join(tempfile.gettempdir(), f"tokenburner_{safe_name}")
        try:
            import boto3
            s3 = boto3.client("s3")
            s3.download_file(_s3_bucket, _s3_key, db_path)
            print(f"[db] Downloaded {_s3_bucket}/{_s3_key} → {db_path}")
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                print(f"[db] No existing database in S3. Starting fresh.")
            else:
                print(f"[db] S3 download failed ({e}). Starting fresh.")

    if not db_path:
        db_path = "tokenburner.sqlite"

    _sqlite_conn = sqlite3.connect(db_path, check_same_thread=False)
    _sqlite_conn.row_factory = sqlite3.Row
    _sqlite_conn.execute("PRAGMA journal_mode=WAL")
    _sqlite_conn.execute("PRAGMA foreign_keys=ON")
    print(f"[db] SQLite mode: {db_path}")
    return _sqlite_conn


def _sqlite_save():
    """Upload modified SQLite back to S3 if in S3 mode."""
    global _dirty
    if not _s3_bucket or not _dirty:
        return
    _dirty = False
    # Force WAL checkpoint so all data is in the main file
    _sqlite_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    import tempfile
    safe_name = _s3_key.replace("/", "_").replace("\\", "_")
    db_path = os.path.join(tempfile.gettempdir(), f"tokenburner_{safe_name}")
    try:
        import boto3
        s3 = boto3.client("s3")
        s3.upload_file(db_path, _s3_bucket, _s3_key)
        print(f"[db] Saved → s3://{_s3_bucket}/{_s3_key}")
    except Exception as e:
        print(f"[db] WARNING: S3 upload failed: {e}")


# ──────────────────────────────────────────────
# Public API — same interface regardless of mode
# ──────────────────────────────────────────────
def query(sql, params=None):
    """Execute a SELECT and return all rows as dicts."""
    if _detect_mode() == "postgres":
        conn = _get_pool().getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            _get_pool().putconn(conn)
    else:
        with _sqlite_lock:
            conn = _get_sqlite()
            translated = _translate_sql(sql)
            translated, params = _translate_params(translated, params)
            try:
                cur = conn.execute(translated, params or [])
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
                return []
            except sqlite3.OperationalError as e:
                print(f"[db] SQLite query error: {e}\n  SQL: {translated}")
                raise


def execute(sql, params=None):
    """Execute an INSERT/UPDATE/DELETE and return rowcount."""
    global _dirty
    if _detect_mode() == "postgres":
        conn = _get_pool().getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                return cur.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            _get_pool().putconn(conn)
    else:
        with _sqlite_lock:
            conn = _get_sqlite()
            translated = _translate_sql(sql)
            translated, params = _translate_params(translated, params)
            try:
                if params:
                    cur = conn.execute(translated, params)
                elif ';' in translated.strip().rstrip(';'):
                    # Multiple statements (e.g., migration files) — use executescript
                    conn.executescript(translated)
                    conn.commit()
                    _dirty = True
                    _sqlite_save()
                    return 0
                else:
                    cur = conn.execute(translated)
                conn.commit()
                _dirty = True
                _sqlite_save()
                return cur.rowcount
            except sqlite3.OperationalError as e:
                conn.rollback()
                print(f"[db] SQLite execute error: {e}\n  SQL: {translated}")
                raise


def transact(statements):
    """Execute multiple statements in a single transaction.
    statements: list of (sql, params) tuples.
    """
    global _dirty
    if _detect_mode() == "postgres":
        conn = _get_pool().getconn()
        try:
            with conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, params)
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _get_pool().putconn(conn)
    else:
        with _sqlite_lock:
            conn = _get_sqlite()
            try:
                for sql, params in statements:
                    translated = _translate_sql(sql)
                    translated, params = _translate_params(translated, params)
                    conn.execute(translated, params or [])
                conn.commit()
                _dirty = True
                _sqlite_save()
            except sqlite3.OperationalError as e:
                conn.rollback()
                print(f"[db] SQLite transact error: {e}")
                raise


def get_mode():
    """Return current database mode: 'postgres' or 'sqlite'."""
    return _detect_mode()
