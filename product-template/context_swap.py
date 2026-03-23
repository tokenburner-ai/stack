#!/usr/bin/env python3
"""context_swap — swap entire product definitions via S3.

Save, load, and switch between different product contexts. Each snapshot
captures the full product state: context file, routes, migrations, frontend,
and database. Same URL, completely different API.

Usage:
    python context_swap.py save <name> [--description "..."] [--max-size-mb 50]
    python context_swap.py load <name>
    python context_swap.py list
    python context_swap.py diff <name>
    python context_swap.py delete <name>

Environment:
    S3_DB_BUCKET    S3 bucket (from base stack)
    PRODUCT_NAME    Product name (default: from .tokenburner.json)
    AWS_PROFILE     AWS CLI profile
"""

import argparse
import json
import os
import sys
import tempfile
import difflib
from datetime import datetime, timezone
from pathlib import Path

import boto3

# ─── Config ──────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent

def _load_config():
    """Load .tokenburner.json for defaults."""
    cfg_path = PROJECT_ROOT / ".tokenburner.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text())
    return {}

_cfg = _load_config()
BUCKET = os.environ.get("S3_DB_BUCKET", "")
PRODUCT = os.environ.get("PRODUCT_NAME", _cfg.get("product_name", "my-product"))
CONTEXTS_PREFIX = f"{PRODUCT}/contexts/"

# Files that define the product (relative to project root)
PRODUCT_FILES = [
    "tokenburner.md",
    "app/main.py",
]
PRODUCT_DIRS = [
    "migrations",
    "static",
]


def _s3():
    profile = os.environ.get("AWS_PROFILE", _cfg.get("aws_profile"))
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client("s3")


def _context_prefix(name):
    return f"{CONTEXTS_PREFIX}{name}/"


def _discover_bucket():
    """Find the S3 bucket from base stack if not set."""
    global BUCKET
    if BUCKET:
        return BUCKET
    # Try CloudFormation export
    profile = os.environ.get("AWS_PROFILE", _cfg.get("aws_profile"))
    region = os.environ.get("AWS_REGION", _cfg.get("region", "us-west-2"))
    session = boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)
    cfn = session.client("cloudformation")
    try:
        paginator = cfn.get_paginator("list_exports")
        for page in paginator.paginate():
            for export in page["Exports"]:
                if export["Name"] == "tokenburner-db-snapshots-bucket":
                    BUCKET = export["Value"]
                    return BUCKET
    except Exception:
        pass
    print("Error: Could not find S3 bucket. Set S3_DB_BUCKET or deploy the base stack first.")
    sys.exit(1)


# ─── Save ────────────────────────────────────────────

def save_context(name, description="", max_size_mb=50):
    """Save current product state to S3."""
    _discover_bucket()
    s3 = _s3()
    prefix = _context_prefix(name)

    # ─── Size guardrail: calculate total before uploading ───
    total_bytes = 0
    files_to_upload = []

    for rel_path in PRODUCT_FILES:
        full_path = PROJECT_ROOT / rel_path
        if full_path.exists():
            size = full_path.stat().st_size
            total_bytes += size
            files_to_upload.append((rel_path, full_path, size))

    for dir_name in PRODUCT_DIRS:
        dir_path = PROJECT_ROOT / dir_name
        if dir_path.is_dir():
            for file_path in sorted(dir_path.rglob("*")):
                if file_path.is_file() and "__pycache__" not in str(file_path):
                    rel = str(file_path.relative_to(PROJECT_ROOT))
                    size = file_path.stat().st_size
                    total_bytes += size
                    files_to_upload.append((rel, file_path, size))

    total_mb = total_bytes / (1024 * 1024)
    if total_mb > max_size_mb:
        print(f"Error: Context too large ({total_mb:.1f} MB, limit is {max_size_mb} MB)")
        print(f"Largest files:")
        for rel, _, size in sorted(files_to_upload, key=lambda x: x[2], reverse=True)[:5]:
            print(f"  {size:>10,} bytes  {rel}")
        print(f"\nUse --max-size-mb {int(total_mb) + 10} to override.")
        sys.exit(1)

    # ─── Upload files ───
    uploaded = []
    for rel_path, full_path, _ in files_to_upload:
        s3_key = f"{prefix}{rel_path}"
        s3.upload_file(str(full_path), BUCKET, s3_key)
        uploaded.append(rel_path)

    # Save the database snapshot too
    db_key = f"{PRODUCT}/dev.sqlite"
    try:
        s3.head_object(Bucket=BUCKET, Key=db_key)
        s3.copy_object(
            Bucket=BUCKET,
            CopySource={"Bucket": BUCKET, "Key": db_key},
            Key=f"{prefix}dev.sqlite",
        )
        uploaded.append("dev.sqlite")
    except Exception:
        pass  # No database yet, that's fine

    # Write manifest
    manifest = {
        "name": name,
        "description": description,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "product": PRODUCT,
        "files": uploaded,
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{prefix}manifest.json",
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )

    print(f"Saved context '{name}' ({len(uploaded)} files)")
    for f in uploaded:
        print(f"  {f}")
    if description:
        print(f"  Description: {description}")


# ─── Load ────────────────────────────────────────────

def load_context(name):
    """Load a product context from S3, replacing local files."""
    _discover_bucket()
    s3 = _s3()
    prefix = _context_prefix(name)

    # Read manifest
    try:
        body = s3.get_object(Bucket=BUCKET, Key=f"{prefix}manifest.json")["Body"].read()
        manifest = json.loads(body)
    except Exception:
        print(f"Error: Context '{name}' not found.")
        sys.exit(1)

    restored = []

    for rel_path in manifest["files"]:
        if rel_path == "dev.sqlite":
            continue  # Handle database separately
        s3_key = f"{prefix}{rel_path}"
        local_path = PROJECT_ROOT / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(BUCKET, s3_key, str(local_path))
        restored.append(rel_path)

    # Restore database
    if "dev.sqlite" in manifest["files"]:
        db_key = f"{PRODUCT}/dev.sqlite"
        s3.copy_object(
            Bucket=BUCKET,
            CopySource={"Bucket": BUCKET, "Key": f"{prefix}dev.sqlite"},
            Key=db_key,
        )
        restored.append("dev.sqlite (live database replaced)")

    # Clean up migrations that don't exist in this context
    migrations_dir = PROJECT_ROOT / "migrations"
    if migrations_dir.is_dir():
        context_migrations = {f for f in manifest["files"] if f.startswith("migrations/")}
        for existing in migrations_dir.iterdir():
            rel = f"migrations/{existing.name}"
            if existing.is_file() and rel not in context_migrations:
                existing.unlink()
                restored.append(f"{rel} (removed)")

    print(f"Loaded context '{name}' ({len(restored)} files)")
    for f in restored:
        print(f"  {f}")
    print(f"\nDescription: {manifest.get('description', '(none)')}")
    print(f"Saved at: {manifest.get('saved_at', '?')}")
    print(f"\nNext steps:")
    print(f"  1. Review changes: git diff")
    print(f"  2. Redeploy: tokenburner deploy (or cdk deploy)")
    print(f"  3. The same URL will now serve the new API")


# ─── List ────────────────────────────────────────────

def list_contexts():
    """List all saved contexts."""
    _discover_bucket()
    s3 = _s3()

    try:
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix=CONTEXTS_PREFIX, Delimiter="/")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    prefixes = response.get("CommonPrefixes", [])
    if not prefixes:
        print("No saved contexts.")
        return

    contexts = []
    for p in prefixes:
        ctx_name = p["Prefix"].replace(CONTEXTS_PREFIX, "").rstrip("/")
        try:
            body = s3.get_object(Bucket=BUCKET, Key=f"{p['Prefix']}manifest.json")["Body"].read()
            manifest = json.loads(body)
            contexts.append(manifest)
        except Exception:
            contexts.append({"name": ctx_name, "description": "?", "saved_at": "?", "files": []})

    print(f"{'Name':<25} {'Files':>5} {'Saved':>22}   Description")
    print("-" * 85)
    for ctx in sorted(contexts, key=lambda x: x.get("saved_at", "")):
        name = ctx["name"]
        files = len(ctx.get("files", []))
        saved = ctx.get("saved_at", "?")[:19]
        desc = ctx.get("description", "")[:30]
        print(f"{name:<25} {files:>5} {saved:>22}   {desc}")


# ─── Diff ────────────────────────────────────────────

def diff_context(name):
    """Show diff between current files and a saved context."""
    _discover_bucket()
    s3 = _s3()
    prefix = _context_prefix(name)

    # Read manifest
    try:
        body = s3.get_object(Bucket=BUCKET, Key=f"{prefix}manifest.json")["Body"].read()
        manifest = json.loads(body)
    except Exception:
        print(f"Error: Context '{name}' not found.")
        sys.exit(1)

    has_diff = False
    for rel_path in manifest["files"]:
        if rel_path == "dev.sqlite":
            continue  # Can't diff binary
        s3_key = f"{prefix}{rel_path}"
        local_path = PROJECT_ROOT / rel_path

        # Get S3 version
        try:
            s3_body = s3.get_object(Bucket=BUCKET, Key=s3_key)["Body"].read().decode("utf-8")
        except Exception:
            continue

        # Get local version
        if local_path.exists():
            local_body = local_path.read_text()
        else:
            local_body = ""

        if s3_body != local_body:
            has_diff = True
            diff = difflib.unified_diff(
                s3_body.splitlines(keepends=True),
                local_body.splitlines(keepends=True),
                fromfile=f"s3:{name}/{rel_path}",
                tofile=f"local/{rel_path}",
            )
            sys.stdout.writelines(diff)
            print()

    if not has_diff:
        print(f"No differences between current files and context '{name}'.")


# ─── Delete ──────────────────────────────────────────

def delete_context(name):
    """Delete a saved context from S3."""
    _discover_bucket()
    s3 = _s3()
    prefix = _context_prefix(name)

    # List all objects under this context
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    objects = response.get("Contents", [])

    if not objects:
        print(f"Error: Context '{name}' not found.")
        sys.exit(1)

    for obj in objects:
        s3.delete_object(Bucket=BUCKET, Key=obj["Key"])

    print(f"Deleted context '{name}' ({len(objects)} files removed)")


# ─── CLI ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="context_swap — swap product definitions via S3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s save crm-v1 --description "CRM with contacts and deals"
  %(prog)s save inventory --description "Inventory tracker"
  %(prog)s list
  %(prog)s load crm-v1            # swap to CRM — redeploy to go live
  %(prog)s diff inventory          # see what would change
  %(prog)s delete old-experiment
        """,
    )
    sub = parser.add_subparsers(dest="command")

    save_cmd = sub.add_parser("save", help="Save current product state as a named context")
    save_cmd.add_argument("name", help="Context name")
    save_cmd.add_argument("--description", "-d", default="", help="Short description of this context")
    save_cmd.add_argument("--max-size-mb", type=int, default=50, help="Max context size in MB (default: 50)")

    load_cmd = sub.add_parser("load", help="Load a saved context (replaces local files)")
    load_cmd.add_argument("name", help="Context name to load")

    sub.add_parser("list", help="List all saved contexts")
    sub.add_parser("ls", help="List all saved contexts (alias)")

    diff_cmd = sub.add_parser("diff", help="Diff current files against a saved context")
    diff_cmd.add_argument("name", help="Context name to diff against")

    del_cmd = sub.add_parser("delete", help="Delete a saved context")
    del_cmd.add_argument("name", help="Context name to delete")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "save":
        save_context(args.name, args.description, args.max_size_mb)
    elif args.command == "load":
        load_context(args.name)
    elif args.command in ("list", "ls"):
        list_contexts()
    elif args.command == "diff":
        diff_context(args.name)
    elif args.command == "delete":
        delete_context(args.name)


if __name__ == "__main__":
    main()
