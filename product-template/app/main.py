"""Product application — Flask web service."""

import os
from flask import Flask, jsonify, send_from_directory

from db import query, execute
from migrate import run_migrations

app = Flask(__name__, static_folder="../static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")


@app.before_request
def _run_migrations_once():
    """Run migrations on first request, then remove this hook."""
    run_migrations()
    app.before_request_funcs[None].remove(_run_migrations_once)


@app.route("/health")
def health():
    """ALB health check endpoint."""
    try:
        query("SELECT 1")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ─── Add your routes below ───


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
