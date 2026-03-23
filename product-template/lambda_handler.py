"""Lambda entry point — wraps Flask (WSGI) app for Lambda function URL."""

import os
import sys

# Add app/ to path so imports resolve the same as in Docker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

# Fix paths for Lambda's flat bundle layout before importing app
import migrate
migrate.MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

from main import app

# Fix static folder path for Lambda bundle layout
app.static_folder = os.path.join(os.path.dirname(__file__), "static")

from apig_wsgi import make_lambda_handler

handler = make_lambda_handler(app)
