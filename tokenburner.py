#!/usr/bin/env python3
"""Tokenburner CLI — context loader for AI-assisted operations."""

import json
import os
import subprocess
import sys

CONTEXT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "context")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tokenburner.json")

COMMANDS = {
    "deploy":       ("deploy.md",       "Deploy base + product stack, verify, present results"),
    "status":       ("status.md",       "Check stacks, resources, costs, health"),
    "destroy":      ("destroy.md",      "Tear down all tokenburner stacks"),
    "extend":       ("extend-api.md",   "Add new API routes and database tables"),
    "domain":       ("setup-domain.md", "Attach a custom domain and SSL"),
    "upgrade neon": ("upgrade-neon.md", "Migrate from SQLite-on-S3 to Neon Postgres"),
}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"No config found. Creating {CONFIG_FILE}...\n")
        config = {
            "aws_profile": input("AWS profile name [tokenburner]: ").strip() or "tokenburner",
            "region": input("AWS region [us-west-2]: ").strip() or "us-west-2",
            "product_name": input("Product name [demo]: ").strip() or "demo",
        }
        # Verify and capture account ID
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--output", "json"],
            env={**os.environ, "AWS_PROFILE": config["aws_profile"]},
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Error verifying AWS credentials: {result.stderr.strip()}")
            sys.exit(1)
        identity = json.loads(result.stdout)
        config["account_id"] = identity["Account"]
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        print(f"\nConfig saved to {CONFIG_FILE}")
    else:
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    return config


def verify_account(config):
    """Verify AWS credentials match config and print identity."""
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--output", "json"],
        env={**os.environ, "AWS_PROFILE": config["aws_profile"]},
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr.strip()}")
        sys.exit(1)
    identity = json.loads(result.stdout)
    if identity["Account"] != config.get("account_id"):
        print(f"WARNING: Account mismatch!")
        print(f"  Config:  {config.get('account_id')}")
        print(f"  Actual:  {identity['Account']}")
        sys.exit(1)
    return identity


def print_context(filename, config):
    """Read context file and substitute config values."""
    path = os.path.join(CONTEXT_DIR, filename)
    if not os.path.exists(path):
        print(f"Context file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        content = f.read()
    # Substitute placeholders
    content = content.replace("<profile>", config.get("aws_profile", "tokenburner"))
    content = content.replace("<region>", config.get("region", "us-west-2"))
    content = content.replace("<product_name>", config.get("product_name", "demo"))
    content = content.replace("<account_id>", config.get("account_id", "unknown"))
    print(content)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("Tokenburner CLI — context loader for AI-assisted operations\n")
        print("Usage: python3 tokenburner.py <command>\n")
        print("Commands:")
        for cmd, (_, desc) in sorted(COMMANDS.items()):
            print(f"  {cmd:<16} {desc}")
        print(f"\nConfig: {CONFIG_FILE}")
        sys.exit(0)

    # Handle "upgrade neon" as two-word command
    cmd = " ".join(sys.argv[1:]).lower()
    if cmd not in COMMANDS:
        # Try single word
        cmd = sys.argv[1].lower()
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print(f"Run 'python3 tokenburner.py help' for available commands.")
        sys.exit(1)

    filename, description = COMMANDS[cmd]
    config = load_config()
    identity = verify_account(config)

    print(f"{'='*60}")
    print(f"Tokenburner — {description}")
    print(f"{'='*60}")
    print(f"Account:  {identity['Account']}")
    print(f"Profile:  {config['aws_profile']}")
    print(f"Region:   {config['region']}")
    print(f"Product:  {config['product_name']}")
    print(f"{'='*60}\n")

    print_context(filename, config)


if __name__ == "__main__":
    main()
