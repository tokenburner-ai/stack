"""API key authentication — shared between the dashboard and feature Lambdas.

Vendored copy of stack/product-template/app/auth.py, trimmed to the API-key path.
The dashboard does not support Google OAuth (keep it one-piece), so only the
Bearer / X-API-Key / ?key= paths are kept.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps

from flask import request, jsonify

logger = logging.getLogger(__name__)

API_KEYS_TABLE = os.environ.get("API_KEYS_TABLE", "tokenburner-api-keys")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

_dynamodb = None


@dataclass
class Identity:
    method: str
    name: str
    email: str | None = None
    permissions: list = field(default_factory=lambda: ["read"])
    environments: list = field(default_factory=lambda: ["*"])

    @property
    def can_write(self) -> bool:
        return "write" in self.permissions


def _get_table():
    global _dynamodb
    if _dynamodb is None:
        import boto3
        _dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb.Table(API_KEYS_TABLE)


def validate_api_key(key: str) -> Identity | None:
    if not key or not key.startswith("sk_"):
        return None
    try:
        resp = _get_table().get_item(Key={"key_id": key})
        item = resp.get("Item")
        if not item or not item.get("active", True):
            return None
        expires_at = item.get("expires_at")
        if expires_at and datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
            return None
        try:
            _get_table().update_item(
                Key={"key_id": key},
                UpdateExpression="SET last_used_at = :now",
                ExpressionAttributeValues={":now": datetime.now(timezone.utc).isoformat()},
            )
        except Exception:
            pass
        return Identity(
            method="api_key",
            name=item.get("name", key),
            email=item.get("email"),
            permissions=item.get("permissions", ["read"]),
            environments=item.get("environments", ["*"]),
        )
    except Exception:
        logger.exception("API key validation failed")
        return None


def _extract_api_key() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer sk_"):
        return auth[7:]
    header = request.headers.get("X-API-Key", "")
    if header.startswith("sk_"):
        return header
    qs = request.args.get("key", "")
    if qs.startswith("sk_"):
        return qs
    return None


def get_identity() -> Identity | None:
    key = _extract_api_key()
    return validate_api_key(key) if key else None


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        identity = get_identity()
        if not identity:
            return jsonify({"error": "Authentication required"}), 401
        request.identity = identity
        return f(*args, **kwargs)
    return decorated
