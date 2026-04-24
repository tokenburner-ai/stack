"""Product application — Flask web service with Swagger API docs."""

import os
from flask import Flask, jsonify, request, send_from_directory

from db import query, execute, get_mode
from migrate import run_migrations
from auth import register_oauth_routes, require_auth, require_write

app = Flask(__name__, static_folder="../static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

# ─── Swagger / OpenAPI ───────────────────────────────────

try:
    from flasgger import Swagger

    swagger_config = {
        "headers": [],
        "specs": [{"endpoint": "apispec", "route": "/openapi.json"}],
        "static_url_path": "/flasgger_static",
        "swagger_ui": True,
        "specs_route": "/docs",
    }
    swagger_template = {
        "openapi": "3.0.3",
        "info": {
            "title": os.environ.get("PRODUCT_NAME", "Tokenburner Product"),
            "version": "1.0.0",
            "description": "Auto-generated API for your tokenburner product. "
                           "Authenticate with your API key using the Authorize button.",
        },
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey", "in": "header", "name": "Authorization",
                    "description": "API key: `Bearer sk_...`",
                },
            }
        },
        "security": [{"ApiKeyAuth": []}],
    }
    swagger = Swagger(app, config=swagger_config, template=swagger_template)
except ImportError:
    @app.route("/docs")
    def docs_fallback():
        return jsonify({"message": "Install flasgger for Swagger UI"})


# ─── Auth Routes ─────────────────────────────────────────
register_oauth_routes(app)


# ─── Migrations ──────────────────────────────────────────

@app.before_request
def _run_migrations_once():
    run_migrations()
    app.before_request_funcs[None].remove(_run_migrations_once)


# ─── Health + Index ──────────────────────────────────────

@app.route("/health")
def health():
    """Health check.
    ---
    tags: [System]
    security: []
    responses:
      200:
        description: Service is healthy
    """
    try:
        query("SELECT 1")
        return jsonify({"status": "ok", "db_mode": get_mode()}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api-docs")
def api_docs():
    return send_from_directory(app.static_folder, "api-docs.html")


# ─── Accounts CRUD ───────────────────────────────────────

@app.route("/api/accounts", methods=["GET"])
@require_auth
def list_accounts():
    """List all accounts.
    ---
    tags: [Accounts]
    responses:
      200:
        description: Array of accounts
      401:
        description: Authentication required
    """
    rows = query("SELECT id, name, slug, plan, active, created_at FROM accounts ORDER BY id")
    return jsonify(rows)


@app.route("/api/accounts/<int:account_id>", methods=["GET"])
@require_auth
def get_account(account_id):
    """Get account by ID.
    ---
    tags: [Accounts]
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: integer
    responses:
      200:
        description: Account object
      404:
        description: Account not found
    """
    rows = query("SELECT id, name, slug, plan, active, created_at FROM accounts WHERE id = %s", (account_id,))
    if not rows:
        return jsonify({"error": "Account not found"}), 404
    return jsonify(rows[0])


@app.route("/api/accounts", methods=["POST"])
@require_write
def create_account():
    """Create a new account.
    ---
    tags: [Accounts]
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [name, slug]
            properties:
              name:
                type: string
              slug:
                type: string
              plan:
                type: string
                default: free
    responses:
      201:
        description: Created account
      400:
        description: Validation error
    """
    data = request.get_json()
    if not data or not data.get("name") or not data.get("slug"):
        return jsonify({"error": "name and slug required"}), 400
    execute(
        "INSERT INTO accounts (name, slug, plan) VALUES (%s, %s, %s)",
        (data["name"], data["slug"], data.get("plan", "free")),
    )
    rows = query("SELECT id, name, slug, plan, active, created_at FROM accounts WHERE slug = %s", (data["slug"],))
    return jsonify(rows[0]), 201


@app.route("/api/accounts/<int:account_id>", methods=["PUT"])
@require_write
def update_account(account_id):
    """Update an account.
    ---
    tags: [Accounts]
    parameters:
      - name: account_id
        in: path
        required: true
        schema:
          type: integer
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            properties:
              name:
                type: string
              slug:
                type: string
              plan:
                type: string
              active:
                type: boolean
    responses:
      200:
        description: Updated account
      404:
        description: Account not found
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    sets, vals = [], []
    for field in ("name", "slug", "plan", "active"):
        if field in data:
            sets.append(f"{field} = %s")
            vals.append(data[field])
    if not sets:
        return jsonify({"error": "No fields to update"}), 400
    vals.append(account_id)
    execute(f"UPDATE accounts SET {', '.join(sets)} WHERE id = %s", tuple(vals))
    rows = query("SELECT id, name, slug, plan, active, created_at FROM accounts WHERE id = %s", (account_id,))
    if not rows:
        return jsonify({"error": "Account not found"}), 404
    return jsonify(rows[0])


# ─── Users CRUD ──────────────────────────────────────────

@app.route("/api/users", methods=["GET"])
@require_auth
def list_users():
    """List all users.
    ---
    tags: [Users]
    responses:
      200:
        description: Array of users with account and role info
    """
    rows = query("""
        SELECT u.id, u.name, u.email, u.active, u.created_at,
               a.name as account_name, r.name as role_name
        FROM users u
        JOIN accounts a ON a.id = u.account_id
        LEFT JOIN roles r ON r.id = u.role_id
        ORDER BY u.id
    """)
    return jsonify(rows)


@app.route("/api/users/<int:user_id>", methods=["GET"])
@require_auth
def get_user(user_id):
    """Get user by ID.
    ---
    tags: [Users]
    parameters:
      - name: user_id
        in: path
        required: true
        schema:
          type: integer
    responses:
      200:
        description: User object
      404:
        description: User not found
    """
    rows = query("""
        SELECT u.id, u.name, u.email, u.active, u.created_at,
               a.name as account_name, r.name as role_name
        FROM users u
        JOIN accounts a ON a.id = u.account_id
        LEFT JOIN roles r ON r.id = u.role_id
        WHERE u.id = %s
    """, (user_id,))
    if not rows:
        return jsonify({"error": "User not found"}), 404
    return jsonify(rows[0])


@app.route("/api/users", methods=["POST"])
@require_write
def create_user():
    """Create a new user.
    ---
    tags: [Users]
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [name, email, account_id]
            properties:
              name:
                type: string
              email:
                type: string
              account_id:
                type: integer
              role_id:
                type: integer
    responses:
      201:
        description: Created user
      400:
        description: Validation error
    """
    data = request.get_json()
    for field in ("name", "email", "account_id"):
        if not data or not data.get(field):
            return jsonify({"error": f"{field} required"}), 400
    execute(
        "INSERT INTO users (name, email, account_id, role_id) VALUES (%s, %s, %s, %s)",
        (data["name"], data["email"], data["account_id"], data.get("role_id")),
    )
    rows = query("SELECT id, name, email, active, created_at FROM users WHERE email = %s", (data["email"],))
    return jsonify(rows[0]), 201


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@require_write
def update_user(user_id):
    """Update a user.
    ---
    tags: [Users]
    parameters:
      - name: user_id
        in: path
        required: true
        schema:
          type: integer
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            properties:
              name:
                type: string
              email:
                type: string
              role_id:
                type: integer
              active:
                type: boolean
    responses:
      200:
        description: Updated user
      404:
        description: User not found
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    sets, vals = [], []
    for field in ("name", "email", "role_id", "active"):
        if field in data:
            sets.append(f"{field} = %s")
            vals.append(data[field])
    if not sets:
        return jsonify({"error": "No fields to update"}), 400
    vals.append(user_id)
    execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", tuple(vals))
    rows = query("SELECT id, name, email, active, created_at FROM users WHERE id = %s", (user_id,))
    if not rows:
        return jsonify({"error": "User not found"}), 404
    return jsonify(rows[0])


# ─── Roles CRUD ──────────────────────────────────────────

@app.route("/api/roles", methods=["GET"])
@require_auth
def list_roles():
    """List all roles.
    ---
    tags: [Roles]
    responses:
      200:
        description: Array of roles
    """
    return jsonify(query("SELECT id, name, description, permissions, created_at FROM roles ORDER BY id"))


@app.route("/api/roles", methods=["POST"])
@require_write
def create_role():
    """Create a new role.
    ---
    tags: [Roles]
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [name]
            properties:
              name:
                type: string
              description:
                type: string
              permissions:
                type: string
                default: read
    responses:
      201:
        description: Created role
    """
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "name required"}), 400
    execute(
        "INSERT INTO roles (name, description, permissions) VALUES (%s, %s, %s)",
        (data["name"], data.get("description", ""), data.get("permissions", "read")),
    )
    rows = query("SELECT id, name, description, permissions FROM roles WHERE name = %s", (data["name"],))
    return jsonify(rows[0]), 201


# ─── Emails CRUD ─────────────────────────────────────────

@app.route("/api/users/<int:user_id>/emails", methods=["GET"])
@require_auth
def list_user_emails(user_id):
    """List emails for a user.
    ---
    tags: [Emails]
    parameters:
      - name: user_id
        in: path
        required: true
        schema:
          type: integer
    responses:
      200:
        description: Array of email addresses
    """
    return jsonify(query(
        "SELECT id, address, verified, primary_email, created_at FROM emails WHERE user_id = %s ORDER BY id",
        (user_id,),
    ))


@app.route("/api/users/<int:user_id>/emails", methods=["POST"])
@require_write
def add_user_email(user_id):
    """Add an email address to a user.
    ---
    tags: [Emails]
    parameters:
      - name: user_id
        in: path
        required: true
        schema:
          type: integer
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [address]
            properties:
              address:
                type: string
              primary:
                type: boolean
                default: false
    responses:
      201:
        description: Added email
    """
    data = request.get_json()
    if not data or not data.get("address"):
        return jsonify({"error": "address required"}), 400
    execute(
        "INSERT INTO emails (user_id, address, primary_email) VALUES (%s, %s, %s)",
        (user_id, data["address"], data.get("primary", False)),
    )
    rows = query("SELECT id, address, verified, primary_email FROM emails WHERE user_id = %s AND address = %s",
                 (user_id, data["address"]))
    return jsonify(rows[0]), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
