#!/usr/bin/env python3
"""db_branch — git-like database snapshots stored in S3.

Save, restore, and switch between database states like git branches.
Works with any Postgres (local Docker, Aurora, Neon) via pg_dump,
or directly with SQLite-on-S3 dev databases.

Usage:
    python db_branch.py save <name>        Save current DB as a named snapshot
    python db_branch.py restore <name>     Restore DB from a named snapshot
    python db_branch.py list               List all snapshots
    python db_branch.py delete <name>      Delete a snapshot
    python db_branch.py current            Show active snapshot info

Environment:
    S3_DB_BUCKET    S3 bucket for snapshots (required)
    S3_DB_PREFIX    S3 key prefix (default: snapshots/)
    DATABASE_URL    Postgres connection string (for pg_dump/restore mode)
    SQLITE_DB_PATH  Local SQLite file (for SQLite mode)
    S3_DB_KEY       Current S3 SQLite key (for SQLite-on-S3 mode)
    AWS_PROFILE     AWS CLI profile to use
"""

import argparse
import os
import sys
import json
import tempfile
from datetime import datetime, timezone

import boto3

BUCKET = os.environ.get("S3_DB_BUCKET", "tokenburner-db-snapshots")
PREFIX = os.environ.get("S3_DB_PREFIX", "snapshots/")


def s3_client():
    return boto3.client("s3")


def snapshot_key(name):
    return f"{PREFIX}{name}.sqlite"


def metadata_key(name):
    return f"{PREFIX}{name}.meta.json"


def detect_mode():
    """Detect whether we're working with SQLite or Postgres."""
    if os.environ.get("DATABASE_URL") or os.environ.get("DB_SECRET_JSON"):
        return "postgres"
    return "sqlite"


# ──────────────────────────────────────────────
# SQLite snapshots (copy the .sqlite file)
# ──────────────────────────────────────────────

def _get_sqlite_path():
    """Find the current SQLite database file."""
    if os.environ.get("SQLITE_DB_PATH"):
        return os.environ["SQLITE_DB_PATH"]
    if os.environ.get("S3_DB_KEY"):
        safe = os.environ["S3_DB_KEY"].replace("/", "_").replace("\\", "_")
        return os.path.join(tempfile.gettempdir(), f"tokenburner_{safe}")
    return "tokenburner.sqlite"


def save_sqlite(name):
    """Upload current SQLite file to S3 as a named snapshot."""
    s3 = s3_client()
    db_path = _get_sqlite_path()

    if not os.path.exists(db_path):
        print(f"Error: SQLite file not found at {db_path}")
        print("Start your app first to create the database, then snapshot it.")
        sys.exit(1)

    # Upload the database
    s3.upload_file(db_path, BUCKET, snapshot_key(name))

    # Save metadata
    meta = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "sqlite",
        "size_bytes": os.path.getsize(db_path),
        "source": db_path,
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=metadata_key(name),
        Body=json.dumps(meta, indent=2),
        ContentType="application/json",
    )

    print(f"Saved snapshot '{name}' ({meta['size_bytes']:,} bytes)")
    print(f"  s3://{BUCKET}/{snapshot_key(name)}")


def restore_sqlite(name):
    """Download a named snapshot from S3 and replace the current database."""
    s3 = s3_client()
    db_path = _get_sqlite_path()

    # Check it exists
    try:
        s3.head_object(Bucket=BUCKET, Key=snapshot_key(name))
    except s3.exceptions.ClientError:
        print(f"Error: Snapshot '{name}' not found in s3://{BUCKET}/{PREFIX}")
        sys.exit(1)

    # Download
    s3.download_file(BUCKET, snapshot_key(name), db_path)

    # Also update the live S3 key if in S3 mode
    s3_db_key = os.environ.get("S3_DB_KEY")
    if s3_db_key:
        s3.upload_file(db_path, BUCKET, s3_db_key)
        print(f"Restored '{name}' → {db_path}")
        print(f"  Also pushed to s3://{BUCKET}/{s3_db_key} (live database)")
    else:
        print(f"Restored '{name}' → {db_path}")

    print("  Restart your app to pick up the changes.")


# ──────────────────────────────────────────────
# Postgres snapshots (pg_dump / pg_restore)
# ──────────────────────────────────────────────

def save_postgres(name):
    """pg_dump current database to S3."""
    import subprocess
    db_url = os.environ.get("DATABASE_URL", "")
    dump_path = os.path.join(tempfile.gettempdir(), f"tokenburner_{name}.dump")

    print(f"Dumping database...")
    result = subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "-f", dump_path, db_url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"pg_dump failed: {result.stderr}")
        sys.exit(1)

    s3 = s3_client()
    pg_key = f"{PREFIX}{name}.pgdump"
    s3.upload_file(dump_path, BUCKET, pg_key)

    meta = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "postgres",
        "size_bytes": os.path.getsize(dump_path),
        "source": db_url.split("@")[-1] if "@" in db_url else "localhost",
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=metadata_key(name),
        Body=json.dumps(meta, indent=2),
        ContentType="application/json",
    )

    os.remove(dump_path)
    print(f"Saved snapshot '{name}' ({meta['size_bytes']:,} bytes)")
    print(f"  s3://{BUCKET}/{pg_key}")


def restore_postgres(name):
    """Download and pg_restore a named snapshot."""
    import subprocess
    db_url = os.environ.get("DATABASE_URL", "")

    s3 = s3_client()
    pg_key = f"{PREFIX}{name}.pgdump"
    dump_path = os.path.join(tempfile.gettempdir(), f"tokenburner_{name}.dump")

    try:
        s3.download_file(BUCKET, pg_key, dump_path)
    except Exception:
        print(f"Error: Snapshot '{name}' not found (tried {pg_key})")
        sys.exit(1)

    print(f"Restoring '{name}'...")
    result = subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl",
         "-d", db_url, dump_path],
        capture_output=True, text=True,
    )
    os.remove(dump_path)

    if result.returncode != 0 and "ERROR" in result.stderr:
        print(f"pg_restore warnings: {result.stderr[:500]}")
    print(f"Restored '{name}' to database.")


# ──────────────────────────────────────────────
# Shared commands
# ──────────────────────────────────────────────

def list_snapshots():
    """List all snapshots in S3."""
    s3 = s3_client()
    try:
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX)
    except Exception as e:
        print(f"Error listing bucket: {e}")
        sys.exit(1)

    if "Contents" not in response:
        print("No snapshots found.")
        return

    # Find metadata files
    metas = [obj for obj in response["Contents"] if obj["Key"].endswith(".meta.json")]

    if not metas:
        print("No snapshots found.")
        return

    print(f"{'Name':<25} {'Size':>10} {'Created':>25} {'Mode':<10}")
    print("-" * 75)

    for obj in sorted(metas, key=lambda x: x["Key"]):
        try:
            body = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
            meta = json.loads(body)
            size = f"{meta.get('size_bytes', 0):,}B"
            created = meta.get("created_at", "?")[:19]
            mode = meta.get("mode", "?")
            print(f"{meta['name']:<25} {size:>10} {created:>25} {mode:<10}")
        except Exception:
            name = obj["Key"].replace(PREFIX, "").replace(".meta.json", "")
            print(f"{name:<25} {'?':>10} {'?':>25} {'?':<10}")


def delete_snapshot(name):
    """Delete a snapshot from S3."""
    s3 = s3_client()
    keys_to_delete = [
        snapshot_key(name),
        f"{PREFIX}{name}.pgdump",
        metadata_key(name),
    ]
    deleted = 0
    for key in keys_to_delete:
        try:
            s3.delete_object(Bucket=BUCKET, Key=key)
            deleted += 1
        except Exception:
            pass
    print(f"Deleted snapshot '{name}' ({deleted} files removed)")


def current_info():
    """Show info about the current database mode."""
    mode = detect_mode()
    print(f"Mode: {mode}")
    if mode == "sqlite":
        path = _get_sqlite_path()
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        print(f"Path: {path}")
        print(f"Exists: {exists}")
        if exists:
            print(f"Size: {size:,} bytes")
        if os.environ.get("S3_DB_BUCKET"):
            print(f"S3: s3://{os.environ['S3_DB_BUCKET']}/{os.environ.get('S3_DB_KEY', 'dev.sqlite')}")
    else:
        url = os.environ.get("DATABASE_URL", "")
        # Mask password
        if "@" in url:
            parts = url.split("@")
            safe = parts[0].split(":")[0] + ":***@" + parts[1]
        else:
            safe = url
        print(f"URL: {safe}")
    print(f"Bucket: {BUCKET}")
    print(f"Prefix: {PREFIX}")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="db_branch — git-like database snapshots",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s save before-migration     Save current state
  %(prog)s save feature-x            Save a feature branch
  %(prog)s list                      See all snapshots
  %(prog)s restore before-migration  Roll back to saved state
  %(prog)s delete old-snapshot       Clean up
        """,
    )
    sub = parser.add_subparsers(dest="command")

    save_cmd = sub.add_parser("save", help="Save current DB as a named snapshot")
    save_cmd.add_argument("name", help="Snapshot name (like a git branch)")

    restore_cmd = sub.add_parser("restore", help="Restore DB from a snapshot")
    restore_cmd.add_argument("name", help="Snapshot name to restore")

    sub.add_parser("list", help="List all snapshots")
    sub.add_parser("ls", help="List all snapshots (alias)")

    del_cmd = sub.add_parser("delete", help="Delete a snapshot")
    del_cmd.add_argument("name", help="Snapshot name to delete")

    sub.add_parser("current", help="Show current database info")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    mode = detect_mode()

    if args.command == "save":
        if mode == "sqlite":
            save_sqlite(args.name)
        else:
            save_postgres(args.name)
    elif args.command == "restore":
        if mode == "sqlite":
            restore_sqlite(args.name)
        else:
            restore_postgres(args.name)
    elif args.command in ("list", "ls"):
        list_snapshots()
    elif args.command == "delete":
        delete_snapshot(args.name)
    elif args.command == "current":
        current_info()


if __name__ == "__main__":
    main()
