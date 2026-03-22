"""Product application — Flask web service with Swagger API docs."""

import os
from flask import Flask, jsonify, send_from_directory

from db import query, execute
from migrate import run_migrations
from auth import register_oauth_routes, require_auth, require_write, get_identity

app = Flask(__name__, static_folder="../static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

# ─── Swagger / OpenAPI ───────────────────────────────────
# Served at /docs (Swagger UI) and /openapi.json (spec).
# Uses flasgger if installed, otherwise serves a minimal spec.

try:
    from flasgger import Swagger

    swagger_config = {
        "headers": [],
        "specs": [
            {
                "endpoint": "apispec",
                "route": "/openapi.json",
                "rule_filter": lambda rule: True,
                "model_filter": lambda tag: True,
            }
        ],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/docs",
    }

    swagger_template = {
        "openapi": "3.0.3",
        "info": {
            "title": os.environ.get("PRODUCT_NAME", "Tokenburner Product"),
            "version": "1.0.0",
            "description": "API documentation. Authenticate with an API key or Google sign-in.",
        },
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "Authorization",
                    "description": "API key: `Bearer sk_...`",
                },
                "GoogleOAuth": {
                    "type": "oauth2",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": "https://accounts.google.com/o/oauth2/v2/auth",
                            "tokenUrl": "https://oauth2.googleapis.com/token",
                            "scopes": {
                                "openid": "OpenID",
                                "email": "Email",
                                "profile": "Profile",
                            },
                        }
                    },
                },
            }
        },
        "security": [{"ApiKeyAuth": []}, {"GoogleOAuth": []}],
    }

    swagger = Swagger(app, config=swagger_config, template=swagger_template)
    HAS_SWAGGER = True

except ImportError:
    HAS_SWAGGER = False

    @app.route("/docs")
    def docs_fallback():
        return jsonify({
            "message": "Install flasgger for Swagger UI: pip install flasgger",
            "openapi_spec": "/openapi.json",
        })

    @app.route("/openapi.json")
    def openapi_fallback():
        return jsonify({
            "openapi": "3.0.3",
            "info": {
                "title": os.environ.get("PRODUCT_NAME", "Tokenburner Product"),
                "version": "1.0.0",
            },
            "paths": {},
        })


# ─── Auth Routes ─────────────────────────────────────────
register_oauth_routes(app)


# ─── Migrations ──────────────────────────────────────────

@app.before_request
def _run_migrations_once():
    """Run migrations on first request, then remove this hook."""
    run_migrations()
    app.before_request_funcs[None].remove(_run_migrations_once)


# ─── Core Endpoints ──────────────────────────────────────

@app.route("/health")
def health():
    """ALB health check endpoint.
    ---
    responses:
      200:
        description: Service is healthy
    """
    try:
        query("SELECT 1")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ─── Example authenticated endpoints ─────────────────────

@app.route("/api/me")
@require_auth
def me():
    """Get current user identity.
    ---
    security:
      - ApiKeyAuth: []
      - GoogleOAuth: []
    responses:
      200:
        description: Current identity
      401:
        description: Not authenticated
    """
    identity = request.identity
    return jsonify({
        "method": identity.method,
        "name": identity.name,
        "email": identity.email,
        "permissions": identity.permissions,
    })


# ─── Add your routes below ───


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
