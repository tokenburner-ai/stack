"""Background job handler template.

This runs as a Lambda function. Triggered by schedule, webhook, or S3 event.
Connects to Aurora PostgreSQL via Secrets Manager credentials.
"""

import json
import os
import boto3


def _get_db_url():
    """Build database URL from Secrets Manager."""
    client = boto3.client("secretsmanager")
    secret_arn = os.environ["DB_SECRET_ARN"]
    resp = client.get_secret_value(SecretId=secret_arn)
    s = json.loads(resp["SecretString"])
    return f"postgresql://{s['username']}:{s['password']}@{s['host']}:{s.get('port', 5432)}/{s.get('dbname', 'tokenburner')}"


def main(event, context):
    """Lambda entry point."""
    print(f"Job triggered: {json.dumps(event, default=str)}")

    # Example: connect to database
    # import psycopg2
    # conn = psycopg2.connect(_get_db_url())
    # with conn.cursor() as cur:
    #     cur.execute("SELECT count(*) FROM schema_migrations")
    #     print(cur.fetchone())
    # conn.close()

    return {"statusCode": 200, "body": "ok"}
