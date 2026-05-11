"""Tokenburner Dashboard — unified landing page for installed features.

Routes:
  GET  /                   → static dashboard HTML (cards grid)
  GET  /api/features       → list rows in the feature-registry DynamoDB table
  GET  /api/key/verify     → returns identity info for the caller (used by the UI)
  GET  /health             → plain health check (no auth)
"""

import json
import logging
import os

import boto3
from flask import Flask, jsonify, request, send_from_directory

from auth import require_auth, get_identity

logger = logging.getLogger()
logger.setLevel(logging.INFO)

app = Flask(__name__, static_folder="../static")
app.secret_key = os.environ.get("SECRET_KEY", "tokenburner-dashboard")

FEATURE_REGISTRY_TABLE = os.environ.get("FEATURE_REGISTRY_TABLE", "tokenburner-feature-registry")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

_ddb = None


def _registry_table():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _ddb.Table(FEATURE_REGISTRY_TABLE)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/features")
@require_auth
def list_features():
    try:
        resp = _registry_table().scan()
        items = resp.get("Items", [])
        items.sort(key=lambda x: x.get("name", ""))
        return jsonify({"features": items})
    except Exception as e:
        logger.exception("feature list failed")
        return jsonify({"features": [], "error": str(e)}), 500


@app.route("/api/key/verify")
@require_auth
def verify_key():
    identity = request.identity
    return jsonify({
        "authenticated": True,
        "name": identity.name,
        "email": identity.email,
        "permissions": identity.permissions,
        "can_write": identity.can_write,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
