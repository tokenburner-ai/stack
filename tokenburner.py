#!/usr/bin/env python3
"""Tokenburner CLI — install, deploy, and manage the tokenburner stack.

Subcommands
    install              Deploy the base stack, then clone + deploy every feature
                         listed in features.yaml.
    status               Show deployed stacks, dashboard URL, and registered features.
    deploy   <feature>   Deploy (or redeploy) a single feature by name, or 'base'.
    destroy  [feature]   Tear down a single feature stack, or (without args) the
                         whole tokenburner stack after a confirmation prompt.
    domain   <domain>    Attach a custom domain to the dashboard (stubbed; prints
                         next-step instructions for now).
    sso      enable      Write Google OAuth credentials to Secrets Manager so
                         features can swap API-key gates for Google sign-in.
    context  <name>      Legacy: print a context markdown file (deploy, status,
                         destroy, extend, domain, upgrade neon, swap). Kept so
                         existing AI-assistant workflows still work.

First run prompts for an AWS profile + region and writes .tokenburner.json.
The bootstrap API key from the base stack is cached at ~/.tokenburner/credentials
(mode 0600) after the first successful install.
"""

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

try:
    import yaml
except ImportError:
    yaml = None  # required for install/deploy/status; checked lazily

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, ".tokenburner.json")
CONTEXT_DIR = os.path.join(HERE, "context")
FEATURES_YAML = os.path.join(HERE, "features.yaml")
FEATURES_DIR = os.path.join(HERE, "features")
CREDS_FILE = os.path.join(pathlib.Path.home(), ".tokenburner", "credentials")
BASE_STACK_DIR = os.path.join(HERE, "base-stack", "cdk")
BASE_STACK_NAME = "tokenburner-base"

LEGACY_CONTEXT_COMMANDS = {
    "deploy":       ("deploy.md",       "Deploy base + product stack, verify, present results"),
    "status":       ("status.md",       "Check stacks, resources, costs, health"),
    "destroy":      ("destroy.md",      "Tear down all tokenburner stacks"),
    "extend":       ("extend-api.md",   "Add new API routes and database tables"),
    "domain":       ("setup-domain.md", "Attach a custom domain and SSL"),
    "upgrade neon": ("upgrade-neon.md", "Migrate from SQLite-on-S3 to Neon Postgres"),
    "swap":         ("swap-context.md", "Save, load, and switch between product contexts"),
}


# ─── Config + AWS helpers ────────────────────────────────

def load_config(interactive: bool = True) -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    if not interactive:
        sys.exit(f"No config at {CONFIG_FILE}. Run `tokenburner install` first.")
    print(f"No config found. Creating {CONFIG_FILE}...\n")
    cfg = {
        "aws_profile": input("AWS profile name [tokenburner]: ").strip() or "tokenburner",
        "region": input("AWS region [us-west-2]: ").strip() or "us-west-2",
        "product_name": input("Product name [demo]: ").strip() or "demo",
    }
    identity = run_aws(["sts", "get-caller-identity"], profile=cfg["aws_profile"])
    cfg["account_id"] = identity["Account"]
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"\nConfig saved to {CONFIG_FILE}")
    return cfg


def run_aws(args: list, profile: str, region: str | None = None, parse: bool = True):
    cmd = ["aws", "--profile", profile] + args
    if region:
        cmd += ["--region", region]
    if parse:
        cmd += ["--output", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"AWS error: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout) if parse and result.stdout.strip() else result.stdout


def verify_account(config: dict) -> dict:
    identity = run_aws(
        ["sts", "get-caller-identity"],
        profile=config["aws_profile"], region=config["region"],
    )
    if identity["Account"] != config.get("account_id"):
        sys.exit(f"Account mismatch. Config expects {config.get('account_id')}, got {identity['Account']}.")
    return identity


# ─── Credentials cache ────────────────────────────────────

def save_creds(account: str, region: str, api_key: str, dashboard_url: str) -> None:
    os.makedirs(os.path.dirname(CREDS_FILE), exist_ok=True)
    payload = {
        "account_id": account,
        "region": region,
        "bootstrap_api_key": api_key,
        "dashboard_url": dashboard_url,
    }
    with open(CREDS_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    os.chmod(CREDS_FILE, 0o600)


def load_creds() -> dict | None:
    if not os.path.exists(CREDS_FILE):
        return None
    with open(CREDS_FILE) as f:
        return json.load(f)


# ─── features.yaml ────────────────────────────────────────

def load_features() -> list[dict]:
    if yaml is None:
        sys.exit("Install PyYAML first: pip install pyyaml")
    if not os.path.exists(FEATURES_YAML):
        return []
    with open(FEATURES_YAML) as f:
        return yaml.safe_load(f).get("features", [])


def find_feature(name: str) -> dict:
    for f in load_features():
        if f["name"] == name:
            return f
    sys.exit(f"Unknown feature: {name}. Known features: {', '.join(f['name'] for f in load_features())}")


# ─── CDK helpers ──────────────────────────────────────────

def _cdk_cmd() -> list:
    """Prefer cdk if on PATH, else fall back to npx cdk."""
    if shutil.which("cdk"):
        return ["cdk"]
    if shutil.which("npx"):
        return ["npx", "cdk"]
    sys.exit("Neither `cdk` nor `npx` found on PATH. Install aws-cdk: npm install -g aws-cdk")


def _cdk_env(config: dict) -> dict:
    """Build subprocess env for cdk that always deploys to config['region'].

    Strips any AWS_REGION / AWS_DEFAULT_REGION inherited from the parent shell
    so a user whose shell has AWS_REGION pinned to a different region still
    gets the deploy they asked for. Both variables are re-set explicitly
    because boto3 and the CDK CLI check different precedence orders.
    """
    region = config["region"]
    env = dict(os.environ)
    for k in ("AWS_REGION", "AWS_DEFAULT_REGION", "CDK_DEFAULT_REGION", "CDK_DEFAULT_ACCOUNT", "AWS_PROFILE"):
        env.pop(k, None)
    env["AWS_PROFILE"] = config["aws_profile"]
    env["AWS_REGION"] = region
    env["AWS_DEFAULT_REGION"] = region
    env["CDK_DEFAULT_REGION"] = region
    env["CDK_DEFAULT_ACCOUNT"] = config["account_id"]
    return env


def cdk_deploy(cdk_dir: str, stack_name: str | None, config: dict, context: dict | None = None) -> None:
    args = _cdk_cmd() + ["deploy"]
    if stack_name:
        args.append(stack_name)
    args += ["--require-approval", "never"]
    for k, v in (context or {}).items():
        args += ["-c", f"{k}={v}"]
    print(f"\n→ cdk deploy {stack_name or ''}  (in {cdk_dir})  region={config['region']}")
    result = subprocess.run(args, cwd=cdk_dir, env=_cdk_env(config))
    if result.returncode != 0:
        sys.exit(f"cdk deploy failed for {stack_name or cdk_dir}")


def cdk_destroy(cdk_dir: str, stack_name: str, config: dict) -> None:
    print(f"\n→ cdk destroy {stack_name}  (in {cdk_dir})  region={config['region']}")
    result = subprocess.run(
        _cdk_cmd() + ["destroy", stack_name, "--force"],
        cwd=cdk_dir, env=_cdk_env(config),
    )
    if result.returncode != 0:
        sys.exit(f"cdk destroy failed for {stack_name}")


def cfn_outputs(stack_name: str, config: dict) -> dict:
    data = run_aws(
        ["cloudformation", "describe-stacks", "--stack-name", stack_name],
        profile=config["aws_profile"], region=config["region"],
    )
    stacks = data.get("Stacks") or []
    if not stacks:
        return {}
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


# ─── git helpers ──────────────────────────────────────────

def git_clone_or_pull(repo_url: str, branch: str, dest: str) -> None:
    if os.path.isdir(os.path.join(dest, ".git")):
        print(f"  (already cloned) git pull  {dest}")
        subprocess.run(["git", "-C", dest, "fetch", "origin"], check=True)
        subprocess.run(["git", "-C", dest, "checkout", branch], check=True)
        subprocess.run(["git", "-C", dest, "pull", "--ff-only", "origin", branch], check=True)
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"  git clone {repo_url}  {dest}")
    subprocess.run(["git", "clone", "--branch", branch, repo_url, dest], check=True)


def resolve_feature_dir(feature: dict) -> str:
    """Return the absolute path of the feature's checkout.

    If the feature entry has `path:` (absolute or relative to the stack repo),
    use it directly — no clone. Otherwise clone/pull into features/<name>.
    """
    if feature.get("path"):
        p = feature["path"]
        if not os.path.isabs(p):
            p = os.path.normpath(os.path.join(HERE, p))
        if not os.path.isdir(p):
            sys.exit(f"Feature '{feature['name']}' path does not exist: {p}")
        return p
    dest = os.path.join(FEATURES_DIR, feature["name"])
    if not os.path.isdir(os.path.join(dest, ".git")):
        git_clone_or_pull(feature["repo"], feature["branch"], dest)
    return dest


# ─── Subcommands ──────────────────────────────────────────

def ensure_cdk_bootstrap(config: dict) -> None:
    """Bootstrap CDK in the target region if it isn't already."""
    try:
        run_aws(
            ["cloudformation", "describe-stacks", "--stack-name", "CDKToolkit"],
            profile=config["aws_profile"], region=config["region"],
        )
        return
    except SystemExit:
        pass
    print(f"\nCDK is not bootstrapped in {config['region']}. Bootstrapping now...")
    result = subprocess.run(
        _cdk_cmd() + ["bootstrap", f"aws://{config['account_id']}/{config['region']}"],
        env=_cdk_env(config),
    )
    if result.returncode != 0:
        sys.exit("cdk bootstrap failed")


def cmd_install(args):
    config = load_config(interactive=True)
    verify_account(config)
    requested = set(args.features or [f["name"] for f in load_features()])
    features = [f for f in load_features() if f["name"] in requested]
    missing = requested - {f["name"] for f in features}
    if missing:
        sys.exit(f"Unknown features: {', '.join(missing)}")

    print(f"\nInstalling tokenburner to account {config['account_id']} in {config['region']}.")
    print(f"Base stack + {len(features)} feature(s): {', '.join(f['name'] for f in features) or '(none)'}\n")

    ensure_cdk_bootstrap(config)

    # 1. Base stack
    cdk_deploy(BASE_STACK_DIR, BASE_STACK_NAME, config, context={"dev_mode": "true"})
    outputs = cfn_outputs(BASE_STACK_NAME, config)
    dashboard_url = outputs.get("DashboardUrl", "")
    api_key = outputs.get("BootstrapApiKey", "")
    if not (dashboard_url and api_key):
        sys.exit("Base stack deployed but DashboardUrl/BootstrapApiKey outputs missing.")
    save_creds(config["account_id"], config["region"], api_key, dashboard_url)

    # 2. Each feature
    for feature in features:
        dest = resolve_feature_dir(feature)
        cdk_dir = os.path.join(dest, feature.get("cdk_dir", "cdk"))
        if not os.path.isdir(cdk_dir):
            print(f"  ! {feature['name']}: no {cdk_dir} directory, skipping")
            continue
        cdk_deploy(cdk_dir, feature["stack_name"], config)

    # 3. Summary
    print("\n" + "=" * 60)
    print("tokenburner install complete")
    print("=" * 60)
    print(f"Dashboard:    {dashboard_url}")
    print(f"API key:      {api_key}")
    print(f"Credentials:  {CREDS_FILE}  (mode 0600)")
    print(f"\nOpen: {dashboard_url}/?key={api_key}")


def cmd_status(args):
    config = load_config(interactive=False)
    verify_account(config)

    print(f"\nAccount:     {config['account_id']}")
    print(f"Region:      {config['region']}")
    print(f"Profile:     {config['aws_profile']}\n")

    # Base stack
    try:
        outputs = cfn_outputs(BASE_STACK_NAME, config)
    except SystemExit:
        outputs = {}
    if outputs:
        print(f"base         {BASE_STACK_NAME}  (deployed)")
        if outputs.get("DashboardUrl"):
            print(f"  dashboard: {outputs['DashboardUrl']}")
    else:
        print(f"base         {BASE_STACK_NAME}  (not deployed)")

    # Features
    print()
    creds = load_creds()
    if not creds:
        print("(no creds cache — run `tokenburner install`)")
        return
    registry = run_aws(
        ["dynamodb", "scan", "--table-name", "tokenburner-feature-registry"],
        profile=config["aws_profile"], region=config["region"],
    )
    items = registry.get("Items", [])
    if not items:
        print("features     (none registered)")
        return
    print("features")
    for item in sorted(items, key=lambda i: i.get("name", {}).get("S", "")):
        name = item.get("name", {}).get("S", "?")
        url = item.get("url", {}).get("S", "")
        print(f"  {name:<12} {url}")


def cmd_deploy(args):
    config = load_config(interactive=False)
    verify_account(config)
    if args.feature == "base":
        cdk_deploy(BASE_STACK_DIR, BASE_STACK_NAME, config, context={"dev_mode": "true"})
        return
    feature = find_feature(args.feature)
    dest = resolve_feature_dir(feature)
    cdk_dir = os.path.join(dest, feature.get("cdk_dir", "cdk"))
    cdk_deploy(cdk_dir, feature["stack_name"], config)


def cmd_destroy(args):
    config = load_config(interactive=False)
    verify_account(config)
    if args.feature:
        feature = find_feature(args.feature)
        dest = resolve_feature_dir(feature) if feature.get("path") else os.path.join(FEATURES_DIR, feature["name"])
        cdk_dir = os.path.join(dest, feature.get("cdk_dir", "cdk"))
        if not os.path.isdir(cdk_dir):
            sys.exit(f"{cdk_dir} missing — cannot destroy. Clone the feature first or destroy it via the AWS console.")
        cdk_destroy(cdk_dir, feature["stack_name"], config)
        return
    # Destroy everything — base + all features.
    confirm = input("This will destroy the base stack AND all feature stacks. Type 'destroy' to confirm: ").strip()
    if confirm != "destroy":
        sys.exit("Aborted.")
    for feature in load_features():
        dest = resolve_feature_dir(feature) if feature.get("path") else os.path.join(FEATURES_DIR, feature["name"])
        cdk_dir = os.path.join(dest, feature.get("cdk_dir", "cdk"))
        if os.path.isdir(cdk_dir):
            try:
                cdk_destroy(cdk_dir, feature["stack_name"], config)
            except SystemExit as e:
                print(f"  ! {feature['name']} destroy failed: {e}")
    cdk_destroy(BASE_STACK_DIR, BASE_STACK_NAME, config)


def cmd_domain(args):
    print("Custom domain attachment is not yet implemented.")
    print("For now, set the `domain_name` / `hosted_zone_id` context values on `cdk deploy`:")
    print(f"  cd {BASE_STACK_DIR}")
    print(f"  cdk deploy -c dev_mode=true -c domain_name={args.domain} -c hosted_zone_id=Z...")


def cmd_sso(args):
    if args.action != "enable":
        sys.exit("Usage: tokenburner sso enable")
    config = load_config(interactive=False)
    client_id = input("Google OAuth client_id: ").strip()
    client_secret = input("Google OAuth client_secret: ").strip()
    if not (client_id and client_secret):
        sys.exit("Both values required.")
    secret = json.dumps({"client_id": client_id, "client_secret": client_secret})
    run_aws(
        ["secretsmanager", "put-secret-value",
         "--secret-id", "tokenburner/google-oauth",
         "--secret-string", secret],
        profile=config["aws_profile"], region=config["region"], parse=False,
    )
    print("Updated tokenburner/google-oauth in Secrets Manager.")


def cmd_context(args):
    key = " ".join(args.rest).lower() if args.rest else ""
    if not key or key not in LEGACY_CONTEXT_COMMANDS:
        print("Legacy context loader. Usage:")
        for cmd, (_, desc) in sorted(LEGACY_CONTEXT_COMMANDS.items()):
            print(f"  tokenburner context {cmd:<16} {desc}")
        sys.exit(0 if not key else 1)
    filename, desc = LEGACY_CONTEXT_COMMANDS[key]
    config = load_config(interactive=False)
    verify_account(config)
    print(f"{'=' * 60}\nTokenburner — {desc}\n{'=' * 60}")
    print(f"Account: {config['account_id']}  Region: {config['region']}\n")
    path = os.path.join(CONTEXT_DIR, filename)
    with open(path) as f:
        content = f.read()
    for placeholder, key in (
        ("<profile>", "aws_profile"),
        ("<region>", "region"),
        ("<product_name>", "product_name"),
        ("<account_id>", "account_id"),
    ):
        content = content.replace(placeholder, str(config.get(key, "")))
    print(content)


# ─── Entry point ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="tokenburner", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Deploy the base stack + all features in features.yaml")
    install.add_argument("--features", nargs="+", help="Limit install to specific feature names")
    install.set_defaults(func=cmd_install)

    status = sub.add_parser("status", help="Show deployed stacks + registered features")
    status.set_defaults(func=cmd_status)

    deploy = sub.add_parser("deploy", help="Deploy one feature, or 'base'")
    deploy.add_argument("feature", help="Feature name or 'base'")
    deploy.set_defaults(func=cmd_deploy)

    destroy = sub.add_parser("destroy", help="Destroy one feature, or everything with no args")
    destroy.add_argument("feature", nargs="?", help="Feature name (omit to destroy all)")
    destroy.set_defaults(func=cmd_destroy)

    domain = sub.add_parser("domain", help="Attach a custom domain to the dashboard")
    domain.add_argument("domain", help="Domain, e.g. apps.example.com")
    domain.set_defaults(func=cmd_domain)

    sso = sub.add_parser("sso", help="Enable Google OAuth for feature stacks")
    sso.add_argument("action", choices=["enable"])
    sso.set_defaults(func=cmd_sso)

    context = sub.add_parser("context", help="Legacy context-file loader")
    context.add_argument("rest", nargs="*")
    context.set_defaults(func=cmd_context)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
