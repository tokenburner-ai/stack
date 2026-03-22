"""Database connection pool and query helpers."""

import os
import json
import psycopg2
from psycopg2 import pool

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            # Build from Secrets Manager secret (JSON with host, port, username, password, dbname)
            secret_json = os.environ.get("DB_SECRET_JSON")
            if secret_json:
                s = json.loads(secret_json)
                database_url = f"postgresql://{s['username']}:{s['password']}@{s['host']}:{s.get('port', 5432)}/{s.get('dbname', 'tokenburner')}"
            else:
                database_url = "postgresql://tokenburner:tokenburner@localhost:5432/tokenburner"
        _pool = pool.ThreadedConnectionPool(1, 10, database_url)
    return _pool


def query(sql, params=None):
    """Execute a SELECT and return all rows as dicts."""
    conn = _get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        _get_pool().putconn(conn)


def execute(sql, params=None):
    """Execute an INSERT/UPDATE/DELETE and return rowcount."""
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


def transact(statements):
    """Execute multiple statements in a single transaction.
    statements: list of (sql, params) tuples.
    """
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
