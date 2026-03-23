"""Authentication — API Keys + Google OAuth.

Two auth paths:
1. API Keys (programmatic): Authorization: Bearer sk_... or X-API-Key: sk_...
2. Google OAuth (human users): Browser-based sign-in flow

API keys are validated against the shared DynamoDB table (tokenburner-api-keys).
Google OAuth uses credentials from Secrets Manager.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps

from flask import request, jsonify, session, redirect

logger = logging.getLogger(__name__)

API_KEYS_TABLE = os.environ.get("API_KEYS_TABLE", "tokenburner-api-keys")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

_dynamodb = None


# ─── Identity ────────────────────────────────────────────

@dataclass
class Identity:
    """Authenticated user or service identity."""
    method: str  # "api_key" or "google"
    name: str
    email: str | None = None
    permissions: list = field(default_factory=lambda: ["read"])
    environments: list = field(default_factory=lambda: ["*"])

    @property
    def can_write(self) -> bool:
        return "write" in self.permissions

    @property
    def can_read(self) -> bool:
        return "read" in self.permissions


# ─── DynamoDB ────────────────────────────────────────────

def _get_api_keys_table():
    global _dynamodb
    if _dynamodb is None:
        import boto3
        _dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb.Table(API_KEYS_TABLE)


# ─── API Key Auth ────────────────────────────────────────

def validate_api_key(key: str) -> Identity | None:
    """Validate an API key against DynamoDB. Returns Identity or None."""
    if not key or not key.startswith("sk_"):
        return None

    try:
        table = _get_api_keys_table()
        resp = table.get_item(Key={"key_id": key})
        item = resp.get("Item")

        if not item:
            return None
        if not item.get("active", True):
            return None

        # Check expiration
        expires_at = item.get("expires_at")
        if expires_at:
            if datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
                return None

        # Update last_used_at (fire-and-forget)
        try:
            table.update_item(
                Key={"key_id": key},
                UpdateExpression="SET last_used_at = :now",
                ExpressionAttributeValues={
                    ":now": datetime.now(timezone.utc).isoformat()
                },
            )
        except Exception:
            pass  # non-critical

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
    """Extract API key from request headers or query params."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer sk_"):
        return auth[7:]

    api_key = request.headers.get("X-API-Key", "")
    if api_key.startswith("sk_"):
        return api_key

    key = request.args.get("key", "")
    if key.startswith("sk_"):
        return key

    return None


# ─── Google OAuth ────────────────────────────────────────

def get_google_auth_url(redirect_uri: str) -> str:
    from urllib.parse import urlencode
    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def exchange_google_code(code: str, redirect_uri: str) -> Identity | None:
    import urllib.request
    import urllib.parse

    data = urllib.parse.urlencode({
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()

    try:
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())

        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        with urllib.request.urlopen(req) as resp:
            user_info = json.loads(resp.read())

        return Identity(
            method="google",
            name=user_info.get("name", user_info.get("email", "Unknown")),
            email=user_info.get("email"),
            permissions=["read", "write"],
            environments=["*"],
        )

    except Exception:
        logger.exception("Google OAuth exchange failed")
        return None


# ─── Middleware / Decorators ─────────────────────────────

def get_identity() -> Identity | None:
    api_key = _extract_api_key()
    if api_key:
        return validate_api_key(api_key)

    if session.get("user_email"):
        return Identity(
            method="google",
            name=session.get("user_name", session["user_email"]),
            email=session["user_email"],
            permissions=session.get("permissions", ["read", "write"]),
            environments=["*"],
        )

    return None


def require_auth(f):
    """Decorator: require authentication (API key or Google session)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        identity = get_identity()
        if not identity:
            return jsonify({"error": "Authentication required"}), 401
        request.identity = identity
        return f(*args, **kwargs)
    return decorated


def require_write(f):
    """Decorator: require write permission."""
    @wraps(f)
    def decorated(*args, **kwargs):
        identity = get_identity()
        if not identity:
            return jsonify({"error": "Authentication required"}), 401
        if not identity.can_write:
            return jsonify({"error": "Write permission required"}), 403
        request.identity = identity
        return f(*args, **kwargs)
    return decorated


# ─── OAuth Routes ──────────────────────────────────────

def register_oauth_routes(app):
    @app.route("/auth/login")
    def auth_login():
        redirect_uri = request.url_root.rstrip("/") + "/auth/callback"
        return redirect(get_google_auth_url(redirect_uri))

    @app.route("/auth/callback")
    def auth_callback():
        code = request.args.get("code")
        if not code:
            return jsonify({"error": "Missing authorization code"}), 400
        redirect_uri = request.url_root.rstrip("/") + "/auth/callback"
        identity = exchange_google_code(code, redirect_uri)
        if not identity:
            return jsonify({"error": "Authentication failed"}), 401
        session["user_email"] = identity.email
        session["user_name"] = identity.name
        session["permissions"] = identity.permissions
        return redirect("/")

    @app.route("/auth/logout")
    def auth_logout():
        session.clear()
        return redirect("/")

    @app.route("/auth/status")
    def auth_status():
        identity = get_identity()
        if identity:
            return jsonify({
                "authenticated": True,
                "method": identity.method,
                "name": identity.name,
                "email": identity.email,
                "permissions": identity.permissions,
            })
        return jsonify({"authenticated": False})
