#!/usr/bin/env python3
"""Tokenburner API Key Management CLI.

Create, list, revoke, and delete API keys in the shared DynamoDB table.

Usage:
    python manage_keys.py list
    python manage_keys.py create "My App" --email user@example.com
    python manage_keys.py create "CI Pipeline" --permissions read write --environments dev
    python manage_keys.py revoke sk_abc123...
    python manage_keys.py activate sk_abc123...
    python manage_keys.py delete sk_abc123...
    python manage_keys.py inspect sk_abc123...
"""

import argparse
import json
import secrets
from datetime import datetime, timezone

import boto3

TABLE_NAME = "tokenburner-api-keys"


def _table(region="us-west-2"):
    return boto3.resource("dynamodb", region_name=region).Table(TABLE_NAME)


def generate_key_id() -> str:
    """Generate a new API key: sk_ + 32 hex characters."""
    return f"sk_{secrets.token_hex(16)}"


def cmd_list(args):
    """List all API keys."""
    table = _table(args.region)
    resp = table.scan()
    items = sorted(resp["Items"], key=lambda x: x.get("created_at", ""), reverse=True)

    if not items:
        print("No API keys found.")
        return

    print(f"{'KEY ID':<40} {'NAME':<25} {'ACTIVE':<8} {'PERMISSIONS':<15} {'LAST USED':<22}")
    print("─" * 110)
    for item in items:
        key_id = item["key_id"]
        name = item.get("name", "—")[:24]
        active = "yes" if item.get("active", True) else "NO"
        perms = ",".join(item.get("permissions", ["read"]))
        last_used = item.get("last_used_at", "never")[:21]
        print(f"{key_id:<40} {name:<25} {active:<8} {perms:<15} {last_used:<22}")


def cmd_create(args):
    """Create a new API key."""
    table = _table(args.region)
    key_id = generate_key_id()

    item = {
        "key_id": key_id,
        "name": args.name,
        "active": True,
        "permissions": args.permissions or ["read"],
        "environments": args.environments or ["*"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "manage_keys",
    }
    if args.email:
        item["email"] = args.email
    if args.description:
        item["description"] = args.description

    table.put_item(Item=item)

    print(f"Created API key:")
    print(f"  key_id:       {key_id}")
    print(f"  name:         {args.name}")
    print(f"  permissions:  {item['permissions']}")
    print(f"  environments: {item['environments']}")
    print()
    print(f"  SAVE THIS KEY — it cannot be retrieved later:")
    print(f"  {key_id}")


def cmd_revoke(args):
    """Revoke (deactivate) an API key."""
    table = _table(args.region)
    table.update_item(
        Key={"key_id": args.key_id},
        UpdateExpression="SET active = :false",
        ExpressionAttributeValues={":false": False},
    )
    print(f"Revoked: {args.key_id}")


def cmd_activate(args):
    """Re-activate a revoked API key."""
    table = _table(args.region)
    table.update_item(
        Key={"key_id": args.key_id},
        UpdateExpression="SET active = :true",
        ExpressionAttributeValues={":true": True},
    )
    print(f"Activated: {args.key_id}")


def cmd_delete(args):
    """Permanently delete an API key."""
    table = _table(args.region)
    table.delete_item(Key={"key_id": args.key_id})
    print(f"Deleted: {args.key_id}")


def cmd_inspect(args):
    """Show full details of an API key."""
    table = _table(args.region)
    resp = table.get_item(Key={"key_id": args.key_id})
    item = resp.get("Item")
    if not item:
        print(f"Key not found: {args.key_id}")
        return
    print(json.dumps(item, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Tokenburner API Key Management")
    parser.add_argument("--region", default="us-west-2", help="AWS region")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all API keys")

    create = sub.add_parser("create", help="Create a new API key")
    create.add_argument("name", help="Human-readable key name")
    create.add_argument("--email", help="Owner email")
    create.add_argument("--description", help="Key purpose")
    create.add_argument("--permissions", nargs="+", default=["read"],
                        help="Permissions: read, write (default: read)")
    create.add_argument("--environments", nargs="+", default=["*"],
                        help="Environments: dev, prd, * (default: *)")

    revoke = sub.add_parser("revoke", help="Revoke an API key")
    revoke.add_argument("key_id", help="Key ID (sk_...)")

    activate = sub.add_parser("activate", help="Re-activate a revoked key")
    activate.add_argument("key_id", help="Key ID (sk_...)")

    delete = sub.add_parser("delete", help="Permanently delete an API key")
    delete.add_argument("key_id", help="Key ID (sk_...)")

    inspect = sub.add_parser("inspect", help="Show full key details")
    inspect.add_argument("key_id", help="Key ID (sk_...)")

    args = parser.parse_args()
    {
        "list": cmd_list,
        "create": cmd_create,
        "revoke": cmd_revoke,
        "activate": cmd_activate,
        "delete": cmd_delete,
        "inspect": cmd_inspect,
    }[args.command](args)


if __name__ == "__main__":
    main()
