#!/usr/bin/env python3
"""Tokenburner CLI — install, deploy, and manage the tokenburner stack.

Subcommands
    install              Deploy the base stack, then clone + deploy every feature
                         listed in features.yaml.
    status               Show deployed stacks, dashboard URL, and registered features.
    deploy   <feature>   Deploy (or redeploy) a single feature by name, or 'base'.
    destroy  [feature]   Tear down a single feature stack, or (without args) the
                         whole tokenburner stack after a confirmation prompt.
                         Before destroying agent, detaches tier IAM policies from
                         per-account users. Use --purge-retained to delete S3
                         buckets and DDB tables left behind by RETAIN policies.
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
PRODUCT_CDK_DIR = os.path.join(HERE, "product-template", "cdk")
AGENT_IAM_PATH = "/tokenburner-agent/"

# DynamoDB tables that use RemovalPolicy.RETAIN in CDK; survive stack destroy.
RETAINED_DDB_TABLES = (
    "tokenburner-api-keys",
    "tokenburner-feature-registry",
    "tokenburner-agent-accounts",
    "tokenburner-agent-context",
    "tokenburner-chat",
    "tokendrive-index",
)

# S3 buckets created with RemovalPolicy.RETAIN (or orphaned after failed destroy).
# Drive uses the tokendrive-* prefix; other features use tokenburner-*.
RETAINED_S3_BUCKET_PREFIXES = ("tokenburner-", "tokendrive-")

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

def _detect_profile_and_region(profile_arg: str | None, region_arg: str | None) -> tuple[str, str]:
    """Pick AWS profile + region without prompting.

    Precedence:
    1. CLI flags (--profile, --region)
    2. Environment variables (AWS_PROFILE, AWS_REGION/AWS_DEFAULT_REGION)
    3. AWS CLI defaults (`aws configure get region`)
    4. Hard defaults: profile=default, region=us-west-2

    Verifies the credential is usable via `aws sts get-caller-identity`. If
    the call fails the user gets a one-line error pointing at `aws configure`.
    """
    profile = profile_arg or os.environ.get("AWS_PROFILE") or "default"
    region = (
        region_arg
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )
    if not region:
        # Try the profile's configured region.
        try:
            r = subprocess.run(
                ["aws", "configure", "get", "region", "--profile", profile],
                capture_output=True, text=True, check=False,
            )
            if r.returncode == 0 and r.stdout.strip():
                region = r.stdout.strip()
        except Exception:
            pass
    if not region:
        region = "us-west-2"
    return profile, region


def load_config(
    interactive: bool = True,
    profile_arg: str | None = None,
    region_arg: str | None = None,
) -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        if profile_arg:
            cfg["aws_profile"] = profile_arg
        if region_arg:
            cfg["region"] = region_arg
        return cfg
    if not interactive:
        sys.exit(f"No config at {CONFIG_FILE}. Run `tokenburner install` first.")

    profile, region = _detect_profile_and_region(profile_arg, region_arg)
    print(f"Detecting AWS account...  (profile={profile}, region={region})")
    try:
        identity = run_aws(["sts", "get-caller-identity"], profile=profile, region=region)
    except SystemExit:
        sys.exit(
            "Could not call `aws sts get-caller-identity`. Run `aws configure` "
            "(or `aws configure --profile <name>`) and try again."
        )

    cfg = {
        "aws_profile": profile,
        "region": region,
        "product_name": "demo",
        "account_id": identity["Account"],
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"Config saved to {CONFIG_FILE}: account={cfg['account_id']}, region={cfg['region']}")
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
    # Put the managed virtualenv first on PATH so the `python3 app.py` in every
    # cdk.json runs the interpreter the CDK requirements were installed into,
    # rather than whichever python3 the shell happens to resolve.
    if os.path.isfile(_cdk_venv_python()):
        env["PATH"] = _cdk_venv_bin() + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = CDK_VENV_DIR
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


CDK_VENV_DIR = os.path.join(HERE, ".venv-cdk")


def _cdk_venv_bin() -> str:
    """Directory holding the managed venv's executables."""
    return os.path.join(CDK_VENV_DIR, "Scripts" if os.name == "nt" else "bin")


def _cdk_venv_python() -> str:
    return os.path.join(_cdk_venv_bin(), "python.exe" if os.name == "nt" else "python")


def _ensure_python3_alias(python: str) -> None:
    """Give a Windows virtualenv a python3 executable.

    Every cdk.json runs `python3 app.py`, but a Windows virtualenv provides
    python.exe with no python3 alias, so PATH would fall through to the host
    interpreter. Runs on every call, not only at creation, so an environment
    made before this existed is repaired rather than silently bypassed.
    """
    if os.name != "nt":
        return
    alias = os.path.join(_cdk_venv_bin(), "python3.exe")
    if os.path.isfile(alias):
        return
    try:
        shutil.copy2(python, alias)
    except OSError as exc:
        sys.exit(
            f"Could not create {alias}, which cdk needs because every "
            f"cdk.json runs `python3 app.py`: {exc}"
        )


def ensure_cdk_venv() -> str:
    """Create the repo-managed virtualenv the CDK apps run in, if absent.

    Every cdk.json runs `"app": "python3 app.py"`, so aws-cdk-lib / constructs
    must be importable by whichever interpreter runs app.py, or `cdk deploy`
    dies at synth with `ModuleNotFoundError: No module named 'aws_cdk'`.
    Nothing in a fresh clone installs them.

    They go in a virtualenv owned by this repo rather than into whatever Python
    happens to be running. Installing into the host interpreter can replace
    packages other software on the machine depends on, and on a PEP 668
    "externally managed" install pip refuses on purpose. Overriding that refusal
    is exactly what the packaging guidance says not to do, so this creates an
    isolated environment instead.
    """
    python = _cdk_venv_python()
    if os.path.isfile(python):
        _ensure_python3_alias(python)
        return python
    print(f"  creating CDK virtualenv in {CDK_VENV_DIR}")
    result = subprocess.run(
        [sys.executable, "-m", "venv", CDK_VENV_DIR], capture_output=True, text=True
    )
    if result.returncode != 0 or not os.path.isfile(python):
        sys.exit(
            f"Could not create a virtualenv at {CDK_VENV_DIR}.\n"
            f"{(result.stderr or result.stdout).strip()}\n"
            f"On Debian/Ubuntu this usually means the venv module is missing: "
            f"install python3-venv and re-run."
        )
    _ensure_python3_alias(python)
    return python


_INSTALLED_REQS: set[str] = set()


def _pip_install(python: str, req: str, force: bool = False) -> None:
    if not os.path.isfile(req):
        return
    if req in _INSTALLED_REQS and not force:
        return
    print(f"  installing {os.path.relpath(req, HERE)} into the CDK virtualenv")
    result = subprocess.run(
        [python, "-m", "pip", "install", "-q", "-r", req], capture_output=True, text=True
    )
    if result.returncode != 0:
        sys.exit(
            f"Failed to install CDK Python deps from {req}:\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    _INSTALLED_REQS.add(req)


def pip_install_cdk_deps(cdk_dir: str) -> None:
    """Make the managed virtualenv ready to run this CDK app.

    Always creates the virtualenv and installs the base stack's requirements as
    the baseline, because a feature may ship no requirements file of its own and
    would otherwise fall through to the host interpreter. Then layers this
    stack's own requirements on top when it has them.
    """
    python = ensure_cdk_venv()
    own = os.path.join(cdk_dir, "requirements.txt")
    base = os.path.join(BASE_STACK_DIR, "requirements.txt")
    # Reassert the baseline for every stack. The environment is shared, so a
    # stack that pinned something different would otherwise leave the next one
    # running against whatever the previous stack installed.
    _pip_install(python, base, force=own != base)
    _pip_install(python, own)


def cdk_destroy(
    cdk_dir: str,
    stack_name: str,
    config: dict,
    context: dict | None = None,
) -> bool:
    """Run cdk destroy. Returns True on success."""
    args = _cdk_cmd() + ["destroy", stack_name, "--force"]
    for k, v in (context or {}).items():
        args += ["-c", f"{k}={v}"]
    pip_install_cdk_deps(cdk_dir)
    print(f"\n→ cdk destroy {stack_name}  (in {cdk_dir})  region={config['region']}")
    result = subprocess.run(args, cwd=cdk_dir, env=_cdk_env(config))
    return result.returncode == 0


def stack_status(stack_name: str, config: dict) -> str | None:
    """Return CloudFormation stack status, or None if the stack does not exist."""
    cmd = [
        "cloudformation", "describe-stacks", "--stack-name", stack_name,
        "--query", "Stacks[0].StackStatus", "--output", "text",
    ]
    result = subprocess.run(
        ["aws", "--profile", config["aws_profile"], "--region", config["region"], *cmd],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def cfn_delete_stack(stack_name: str, config: dict, wait: bool = True) -> None:
    """Start (and optionally wait for) a CloudFormation stack deletion."""
    profile, region = config["aws_profile"], config["region"]
    base = ["aws", "--profile", profile, "--region", region, "cloudformation"]
    subprocess.run([*base, "delete-stack", "--stack-name", stack_name], check=True)
    if wait:
        subprocess.run([*base, "wait", "stack-delete-complete", "--stack-name", stack_name], check=False)


def _agent_tier_policy_arns(config: dict) -> list[str]:
    """ARNs of agent tier managed policies for this region (may be empty if never deployed)."""
    region = config["region"]
    names = (
        f"tokenburner-agent-tier-basic-{region}",
        f"tokenburner-agent-tier-pro-{region}",
    )
    arns: list[str] = []
    for name in names:
        out = subprocess.run(
            [
                "aws", "--profile", config["aws_profile"],
                "iam", "list-policies", "--scope", "Local",
                "--query", f"Policies[?PolicyName=='{name}'].Arn",
                "--output", "text",
            ],
            capture_output=True, text=True,
        )
        if out.returncode == 0 and out.stdout.strip() and out.stdout.strip() != "None":
            arns.append(out.stdout.strip())
    return arns


def cleanup_agent_iam_users(config: dict) -> int:
    """Detach tier policies and delete IAM users created by the agent admin API.

    The agent stack creates managed policies (TierBasic/TierPro) and attaches them
    to per-account users. CloudFormation cannot delete those policies while they are
    still attached, which leaves tokenburner-agent in DELETE_FAILED and blocks base
    stack teardown (export still in use).
    """
    profile = config["aws_profile"]
    tier_arns = _agent_tier_policy_arns(config)
    seen: set[str] = set()
    users: list[str] = []

    for cmd in (
        ["iam", "list-users", "--path-prefix", AGENT_IAM_PATH, "--query", "Users[].UserName", "--output", "text"],
        ["iam", "list-users", "--query", "Users[?starts_with(UserName, `tokenburner-agent-`)].UserName", "--output", "text"],
    ):
        out = subprocess.run(
            ["aws", "--profile", profile, *cmd],
            capture_output=True, text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            for name in out.stdout.split():
                if name and name not in seen:
                    seen.add(name)
                    users.append(name)

    if not users:
        print("  (no tokenburner-agent IAM users to clean up)")
        return 0

    deleted = 0
    for user in users:
        print(f"  cleaning IAM user {user}")
        for arn in tier_arns:
            subprocess.run(
                ["aws", "--profile", profile, "iam", "detach-user-policy",
                 "--user-name", user, "--policy-arn", arn],
                capture_output=True,
            )
        keys_out = subprocess.run(
            ["aws", "--profile", profile, "iam", "list-access-keys", "--user-name", user,
             "--query", "AccessKeyMetadata[].AccessKeyId", "--output", "text"],
            capture_output=True, text=True,
        )
        if keys_out.returncode == 0:
            for key_id in keys_out.stdout.split():
                if key_id:
                    subprocess.run(
                        ["aws", "--profile", profile, "iam", "delete-access-key",
                         "--user-name", user, "--access-key-id", key_id],
                        capture_output=True,
                    )
        rm = subprocess.run(
            ["aws", "--profile", profile, "iam", "delete-user", "--user-name", user],
            capture_output=True, text=True,
        )
        if rm.returncode == 0:
            deleted += 1
        else:
            print(f"  ! could not delete user {user}: {rm.stderr.strip() or rm.stdout.strip()}")
    return deleted


def _aws_base(config: dict, service_region: bool = True) -> list[str]:
    """aws CLI argv prefix for config profile (and region when needed)."""
    cmd = ["aws", "--profile", config["aws_profile"]]
    if service_region:
        cmd += ["--region", config["region"]]
    return cmd


def _empty_s3_bucket(bucket: str, config: dict) -> None:
    """Remove all objects, versions, and delete markers from a bucket."""
    profile = config["aws_profile"]
    while True:
        out = subprocess.run(
            ["aws", "s3api", "list-object-versions", "--bucket", bucket, "--profile", profile],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            break
        data = json.loads(out.stdout or "{}")
        objs = []
        for v in data.get("Versions") or []:
            objs.append({"Key": v["Key"], "VersionId": v["VersionId"]})
        for m in data.get("DeleteMarkers") or []:
            objs.append({"Key": m["Key"], "VersionId": m["VersionId"]})
        if not objs:
            break
        for i in range(0, len(objs), 1000):
            batch = {"Objects": objs[i : i + 1000], "Quiet": True}
            subprocess.run(
                ["aws", "s3api", "delete-objects", "--bucket", bucket,
                 "--delete", json.dumps(batch), "--profile", profile],
                check=True,
            )
    subprocess.run(
        ["aws", "s3", "rm", f"s3://{bucket}", "--recursive", "--profile", profile],
        capture_output=True,
    )


def _is_tokenburner_bucket(name: str, config: dict) -> bool:
    if any(name.startswith(p) for p in RETAINED_S3_BUCKET_PREFIXES):
        return True
    tags = subprocess.run(
        ["aws", "s3api", "get-bucket-tagging", "--bucket", name,
         "--profile", config["aws_profile"]],
        capture_output=True, text=True,
    )
    if tags.returncode != 0:
        return False
    try:
        tagset = json.loads(tags.stdout).get("TagSet", [])
    except json.JSONDecodeError:
        return False
    return any(t.get("Key") == "ManagedBy" and t.get("Value") == "tokenburner" for t in tagset)


def list_retained_s3_buckets(config: dict) -> list[str]:
    """Buckets left after CDK destroy (RETAIN policy or orphaned)."""
    out = subprocess.run(
        ["aws", "s3", "ls", "--profile", config["aws_profile"]],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"Could not list S3 buckets: {out.stderr.strip()}")
    names = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            name = parts[2]
            if _is_tokenburner_bucket(name, config):
                names.append(name)
    return sorted(set(names))


def delete_s3_bucket(bucket: str, config: dict) -> None:
    """Empty a bucket (including versioned objects) and delete it."""
    print(f"  deleting S3 bucket {bucket}")
    _empty_s3_bucket(bucket, config)
    result = subprocess.run(
        ["aws", "s3", "rb", f"s3://{bucket}", "--profile", config["aws_profile"]],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"Could not delete bucket {bucket}: {result.stderr.strip() or result.stdout.strip()}")


def purge_retained_s3_buckets(config: dict) -> None:
    """Delete S3 buckets that CDK retained after stack destroy."""
    buckets = list_retained_s3_buckets(config)
    if not buckets:
        print("  (no retained tokenburner S3 buckets)")
        return
    for bucket in buckets:
        delete_s3_bucket(bucket, config)


def purge_retained_tables(config: dict) -> None:
    """Delete DynamoDB tables that CDK retained after stack destroy."""
    for table in RETAINED_DDB_TABLES:
        desc = subprocess.run(
            [*_aws_base(config), "dynamodb", "describe-table", "--table-name", table],
            capture_output=True, text=True,
        )
        if desc.returncode != 0:
            continue
        print(f"  deleting retained table {table}")
        subprocess.run(
            [*_aws_base(config), "dynamodb", "delete-table", "--table-name", table],
            check=True,
        )


def _product_log_groups(config: dict) -> list[str]:
    """Product stack log groups, or none when that stack is not deployed here.

    destroy_product_stack() reports success when the product template is absent,
    without destroying anything, so its logs must not be queued in that case.
    """
    if not os.path.isdir(PRODUCT_CDK_DIR):
        return []
    return stack_log_groups(config, f"tokenburner-{config.get('product_name', 'demo')}")


def stack_log_groups(config: dict, stack_name: str) -> list[str]:
    """Log groups belonging to a stack's Lambda functions.

    Call this while the stack still exists. Lambda auto-creates
    /aws/lambda/<function-name> on first invocation, outside the stack, so the
    names have to be read from the stack's own resources before it is destroyed.
    Deleting by name prefix instead would also remove log groups belonging to
    features that are still deployed, and any the user created themselves.
    """
    out = subprocess.run(
        [*_aws_base(config), "cloudformation", "list-stack-resources",
         "--stack-name", stack_name,
         "--query", "StackResourceSummaries[?ResourceType=='AWS::Lambda::Function']"
                    ".PhysicalResourceId",
         "--output", "json"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        err = (out.stderr or "").strip()
        # A stack that is already gone is fine; anything else means the mapping
        # is about to be lost, so say so rather than silently deleting nothing.
        if "does not exist" not in err:
            print(f"  ! could not read resources of {stack_name}, its log groups "
                  f"will be left behind: {err.splitlines()[-1] if err else 'unknown error'}")
        return []
    try:
        names = json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        print(f"  ! unreadable resource list for {stack_name}, its log groups "
              f"will be left behind")
        return []
    return [f"/aws/lambda/{n}" for n in names if n]


def purge_log_groups(config: dict, names: list[str]) -> list[str]:
    """Delete the named log groups. Returns the ones that could not be deleted."""
    failed = []
    for name in sorted(set(names)):
        result = subprocess.run(
            [*_aws_base(config), "logs", "delete-log-group", "--log-group-name", name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  deleted log group {name}")
        elif "ResourceNotFoundException" in (result.stderr or ""):
            pass  # already gone
        else:
            print(f"  ! could not delete log group {name}: "
                  f"{(result.stderr or '').strip().splitlines()[-1] if result.stderr else 'unknown error'}")
            failed.append(name)
    return failed


def purge_retained_resources(config: dict, log_groups: list[str] | None = None) -> list[str]:
    """Delete RETAIN DynamoDB tables and S3 buckets, plus the given log groups.

    Log groups are passed in rather than discovered, because they must be read
    from each stack's resources before that stack is destroyed.
    """
    purge_retained_s3_buckets(config)
    purge_retained_tables(config)
    if log_groups:
        return purge_log_groups(config, log_groups)
    return []


def destroy_stack(
    cdk_dir: str,
    stack_name: str,
    config: dict,
    *,
    context: dict | None = None,
    pre_destroy=None,
) -> bool:
    """Destroy one CDK stack, with optional pre-hook and retry for DELETE_FAILED."""
    if pre_destroy:
        pre_destroy(config)
    status = stack_status(stack_name, config)
    if status is None:
        print(f"  {stack_name}: not deployed, skipping")
        return True
    if status == "DELETE_FAILED":
        print(f"  {stack_name}: previous delete failed — retrying after cleanup")
        if pre_destroy:
            pre_destroy(config)
        cfn_delete_stack(stack_name, config, wait=True)
        return stack_status(stack_name, config) is None
    if not os.path.isdir(cdk_dir):
        print(f"  {stack_name}: {cdk_dir} missing — using CloudFormation delete-stack")
        cfn_delete_stack(stack_name, config, wait=True)
        return stack_status(stack_name, config) is None
    if cdk_destroy(cdk_dir, stack_name, config, context=context):
        return True
    # One retry (e.g. agent IAM policies still attached).
    if pre_destroy:
        print(f"  {stack_name}: destroy failed, running pre-destroy cleanup and retrying")
        pre_destroy(config)
        if cdk_destroy(cdk_dir, stack_name, config, context=context):
            return True
    status = stack_status(stack_name, config)
    if status in ("DELETE_FAILED", "UPDATE_COMPLETE", "CREATE_COMPLETE"):
        print(f"  {stack_name}: falling back to CloudFormation delete-stack")
        cfn_delete_stack(stack_name, config, wait=True)
        return stack_status(stack_name, config) is None
    return False


def destroy_product_stack(config: dict) -> bool:
    """Destroy product-template stack if it exists."""
    product = config.get("product_name", "demo")
    stack_name = f"tokenburner-{product}"
    if not os.path.isdir(PRODUCT_CDK_DIR):
        return True
    return destroy_stack(
        PRODUCT_CDK_DIR,
        stack_name,
        config,
        context={"dev_mode": "true", "product_name": product},
    )


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


# Default model for chat — must match chat/cdk/stack.py.
DEFAULT_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def _availability_status(value) -> str:
    """Normalize a Bedrock availability field that may be a scalar or {status: ...}."""
    if isinstance(value, dict):
        return value.get("status", "") or ""
    return value or ""


def _foundation_model_for_profile(config: dict, profile_id: str) -> str:
    """Foundation model id an inference profile routes to, or "" if unknown.

    Inference profile ids carry a routing prefix (us., eu., apac., global.) and
    some carry none, so the foundation model id cannot be derived reliably by
    stripping text. Bedrock reports the profile's own model ARNs, so read it
    from there and fall back to the id itself if it is already a model id.
    """
    try:
        prof = run_aws(
            ["bedrock", "get-inference-profile", "--inference-profile-identifier", profile_id],
            profile=config["aws_profile"], region=config["region"],
        )
    except SystemExit as exc:
        sys.exit(
            f"\nCould not look up the inference profile `{profile_id}` in "
            f"{config['region']}, so the model it routes to is unknown.\n"
            f"The caller may lack bedrock:GetInferenceProfile, the AWS CLI may "
            f"be too old for this operation, or Bedrock may have returned an "
            f"error.\n{exc}\n"
        )
    for model in prof.get("models") or []:
        arn = model.get("modelArn") or ""
        if "/" in arn:
            return arn.rsplit("/", 1)[-1]
    return ""


def ensure_bedrock_model(config: dict, model_id: str = DEFAULT_BEDROCK_MODEL_ID) -> None:
    """Pre-flight: confirm Bedrock reports the configured chat model as usable.

    This is a control-plane check, not a test invocation, so it confirms
    availability rather than proving an end-to-end call will succeed. It needs
    bedrock:ListInferenceProfiles, bedrock:GetInferenceProfile, and
    bedrock:GetFoundationModelAvailability, and stops the install if any of
    them cannot answer.

    Two checks. First, `bedrock list-inference-profiles` must list the model id.
    But profile existence is not invocability: an account can list the inference
    profile while `agreementAvailability` is NOT_AVAILABLE because the Anthropic
    use-case details form was never submitted, so Converse/ConverseStream 500 on
    the very first chat message — exactly the "deploys fine, 500s on first
    message" failure this pre-flight exists to prevent. So second, call
    `bedrock get-foundation-model-availability` and require the model to be
    authorized, entitled, and agreed before deploying chat.
    """
    console_url = (
        f"https://{config['region']}.console.aws.amazon.com/bedrock/home?"
        f"region={config['region']}#/modelaccess"
    )

    try:
        data = run_aws(
            ["bedrock", "list-inference-profiles"],
            profile=config["aws_profile"], region=config["region"],
        )
    except SystemExit:
        # Continuing here would deploy chat unchecked, which is the failure this
        # pre-flight exists to prevent. Bedrock may genuinely be unavailable in
        # the region, or the caller may lack bedrock:ListInferenceProfiles;
        # either way the model cannot be confirmed, so stop and say so.
        sys.exit(
            f"\nCould not query Bedrock in {config['region']}, so `{model_id}` "
            f"cannot be confirmed as usable.\n"
            f"Bedrock may not be offered in this region, or the caller may lack "
            f"bedrock:ListInferenceProfiles.\n"
            f"Check model access here:\n  {console_url}\n"
            f"To install the other features meanwhile:\n"
            f"  python3 tokenburner.py install --features drive forums agent\n"
        )
    profiles = data.get("inferenceProfileSummaries", []) or []
    ids = {p.get("inferenceProfileId", "") for p in profiles}
    if model_id not in ids:
        sys.exit(
            f"\nThe Bedrock model `{model_id}` is not available in {config['region']}.\n"
            f"Enable model access in the AWS console:\n"
            f"  {console_url}\n"
            f"Then re-run `python3 tokenburner.py install`.\n"
        )

    # get-foundation-model-availability wants the underlying foundation model id,
    # while model_id is an inference profile id. Ask Bedrock for the profile's
    # own model ARNs rather than stripping a routing prefix by hand: the prefix
    # set is not fixed (us., eu., apac., global.) and some ids carry none.
    foundation_model_id = _foundation_model_for_profile(config, model_id)
    if not foundation_model_id:
        sys.exit(
            f"\nCould not determine which foundation model `{model_id}` routes to "
            f"in {config['region']}, so its usability cannot be confirmed.\n"
            f"Check the model id in features.yaml, or verify access directly:\n"
            f"  {console_url}\n"
        )
    try:
        avail = run_aws(
            ["bedrock", "get-foundation-model-availability",
             "--model-id", foundation_model_id],
            profile=config["aws_profile"], region=config["region"],
        )
    except SystemExit:
        # Failing open here reintroduces exactly what this check exists to stop:
        # chat deploys and 500s on the first message. Access denied, throttling,
        # an old CLI, or a service error all land here, so stop instead.
        sys.exit(
            f"\nCould not confirm that `{model_id}` is usable in {config['region']}.\n"
            f"get-foundation-model-availability failed. Common causes: the caller "
            f"lacks bedrock:GetFoundationModelAvailability, or the AWS CLI is too "
            f"old for this operation.\n"
            f"Verify access here, then re-run:\n  {console_url}\n"
            f"To install the other features meanwhile:\n"
            f"  python3 tokenburner.py install --features drive forums agent\n"
        )

    authorization = _availability_status(avail.get("authorizationStatus"))
    entitlement = _availability_status(avail.get("entitlementAvailability"))
    region_avail = _availability_status(avail.get("regionAvailability"))
    agreement = _availability_status(avail.get("agreementAvailability"))

    # Require each status explicitly. Treating a missing field as acceptable
    # would report an incomplete response as usable.
    blockers = []
    for label, value, expected in (
        ("authorizationStatus", authorization, "AUTHORIZED"),
        ("entitlementAvailability", entitlement, "AVAILABLE"),
        ("regionAvailability", region_avail, "AVAILABLE"),
        ("agreementAvailability", agreement, "AVAILABLE"),
    ):
        if value != expected:
            blockers.append(f"{label}={value or 'missing'}")

    if blockers:
        if any(b.startswith("agreementAvailability") for b in blockers):
            remedy = ("This is the Anthropic use-case details form. Submit it for "
                      "this account, then request the model in model access:\n")
        else:
            remedy = ("Check model access and that the model is offered in this "
                      "region:\n")
        sys.exit(
            f"\nThe Bedrock model `{model_id}` is listed in {config['region']} but is "
            f"not yet invocable ({', '.join(blockers)}).\n"
            f"{remedy}"
            f"  {console_url}\n"
            f"Then re-run `python3 tokenburner.py install`.\n"
        )

    print(f"Bedrock model OK: {model_id} reported available in {config['region']}.")


def cmd_install(args):
    config = load_config(
        interactive=True,
        profile_arg=getattr(args, "profile", None),
        region_arg=getattr(args, "region", None),
    )
    verify_account(config)
    requested = set(args.features or [f["name"] for f in load_features()])
    features = [f for f in load_features() if f["name"] in requested]
    missing = requested - {f["name"] for f in features}
    if missing:
        sys.exit(f"Unknown features: {', '.join(missing)}")

    print(f"\nInstalling tokenburner to account {config['account_id']} in {config['region']}.")
    print(f"Base stack + {len(features)} feature(s): {', '.join(f['name'] for f in features) or '(none)'}\n")

    # Pre-flight: if chat is requested, verify Bedrock model access in the
    # target region. Better to fail before a 6-minute CloudFront deploy.
    if any(f["name"] == "chat" for f in features):
        ensure_bedrock_model(config)

    ensure_cdk_bootstrap(config)

    # 1. Base stack
    #    Install the base stack's Python CDK runtime deps first; every cdk.json
    #    runs `python3 app.py`, so aws-cdk-lib must be importable before synth.
    print("\nInstalling CDK Python runtime dependencies...")
    pip_install_cdk_deps(BASE_STACK_DIR)
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
        pip_install_cdk_deps(cdk_dir)
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
        pip_install_cdk_deps(BASE_STACK_DIR)
        cdk_deploy(BASE_STACK_DIR, BASE_STACK_NAME, config, context={"dev_mode": "true"})
        return
    feature = find_feature(args.feature)
    dest = resolve_feature_dir(feature)
    cdk_dir = os.path.join(dest, feature.get("cdk_dir", "cdk"))
    # `deploy <feature>` is the documented recovery step after enabling Bedrock
    # model access, so it has to satisfy the same requirements as install.
    pip_install_cdk_deps(cdk_dir)
    cdk_deploy(cdk_dir, feature["stack_name"], config)


def _agent_pre_destroy(config: dict) -> None:
    cleanup_agent_iam_users(config)


def cmd_destroy(args):
    config = load_config(
        interactive=False,
        profile_arg=getattr(args, "profile", None),
        region_arg=getattr(args, "region", None),
    )
    verify_account(config)
    purge = getattr(args, "purge_retained", False)

    collected_log_groups: list[str] = []

    def destroy_one_feature(feature: dict) -> bool:
        dest = resolve_feature_dir(feature) if feature.get("path") else os.path.join(FEATURES_DIR, feature["name"])
        cdk_dir = os.path.join(dest, feature.get("cdk_dir", "cdk"))
        # Read the stack's Lambda functions while the stack still exists, but
        # only queue them for deletion once the stack is actually gone. A stack
        # that failed to destroy is still running and still needs its logs.
        pending = stack_log_groups(config, feature["stack_name"]) if purge else []
        pre = _agent_pre_destroy if feature["name"] == "agent" else None
        if feature["name"] == "agent":
            print("\n→ agent pre-destroy: detach tier policies and remove IAM users")
        ok = destroy_stack(cdk_dir, feature["stack_name"], config, pre_destroy=pre)
        if not ok:
            print(f"  ! {feature['name']} destroy failed, keeping its log groups")
            return False
        collected_log_groups.extend(pending)
        return True

    if args.feature:
        if args.feature == "product":
            pending = _product_log_groups(config) if purge else []
            if not destroy_product_stack(config):
                sys.exit("product stack destroy failed")
            collected_log_groups.extend(pending)
        else:
            feature = find_feature(args.feature)
            if not destroy_one_feature(feature):
                sys.exit(f"destroy failed for feature {args.feature}")
        if purge:
            print("\n→ deleting retained S3 buckets, DynamoDB tables, "
                  f"and {len(collected_log_groups)} log group(s) from this stack")
            undeleted = purge_retained_resources(config, collected_log_groups)
            if undeleted:
                sys.exit(f"{len(undeleted)} log group(s) could not be deleted; "
                         f"the stack itself was destroyed.")
        return

    # Destroy everything — product, features, base.
    confirm = input(
        "This will destroy all tokenburner stacks"
        + (" and retained S3 buckets, DynamoDB tables, and the CloudWatch log "
           "history of every tokenburner Lambda" if purge else "")
        + ". Type 'destroy' to confirm: "
    ).strip()
    if confirm != "destroy":
        sys.exit("Aborted.")

    failed: list[str] = []

    print("\n→ destroying product stack (if deployed)")
    product_pending = _product_log_groups(config) if purge else []
    if destroy_product_stack(config):
        collected_log_groups.extend(product_pending)
    else:
        failed.append("product")

    for feature in load_features():
        if not destroy_one_feature(feature):
            failed.append(feature["name"])

    print("\n→ destroying base stack")
    base_pending = stack_log_groups(config, BASE_STACK_NAME) if purge else []
    if destroy_stack(
        BASE_STACK_DIR,
        BASE_STACK_NAME,
        config,
        context={"dev_mode": "true"},
    ):
        collected_log_groups.extend(base_pending)
    else:
        failed.append("base")

    if purge:
        print("\n→ deleting retained S3 buckets, DynamoDB tables, "
              f"and {len(collected_log_groups)} log group(s) from the destroyed stacks")
        undeleted = purge_retained_resources(config, collected_log_groups)
        if undeleted:
            failed.append(f"{len(undeleted)} log group(s)")

    if os.path.exists(CREDS_FILE):
        os.remove(CREDS_FILE)
        print(f"  removed cached credentials at {CREDS_FILE}")

    if failed:
        sys.exit(f"destroy incomplete for: {', '.join(failed)}")
    print("\nAll tokenburner stacks destroyed.")


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
    install.add_argument("--profile", help="AWS profile to use (overrides AWS_PROFILE env)")
    install.add_argument("--region", help="AWS region to deploy into (default: profile region or us-west-2)")
    install.set_defaults(func=cmd_install)

    status = sub.add_parser("status", help="Show deployed stacks + registered features")
    status.set_defaults(func=cmd_status)

    deploy = sub.add_parser("deploy", help="Deploy one feature, or 'base'")
    deploy.add_argument("feature", help="Feature name or 'base'")
    deploy.set_defaults(func=cmd_deploy)

    destroy = sub.add_parser("destroy", help="Destroy one feature, or everything with no args")
    destroy.add_argument(
        "feature", nargs="?",
        help="Feature name, 'product', or omit to destroy all",
    )
    destroy.add_argument(
        "--purge-retained",
        action="store_true",
        help="After stacks are gone, delete RETAIN S3 buckets (forums, drive, etc.) and DynamoDB tables",
    )
    destroy.add_argument("--profile", help="AWS profile to use (overrides AWS_PROFILE env and saved config)")
    destroy.add_argument("--region", help="AWS region to target (overrides saved config)")
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
