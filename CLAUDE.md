# Tokenburner Stack — install guide for Claude

You are helping the user install the tokenburner stack into their AWS account.
The goal is that from a fresh clone of this repo the user gets a working
dashboard URL with working feature cards in about 30 minutes, without ever
opening a CDK file. Most of that time is CloudFront waiting for eventual
consistency on each feature — there's nothing the user can do to speed it up,
so set expectations honestly up front.

## Decisions Claude makes on behalf of the user

- **Region:** `us-west-2` by default unless the user has a strong preference.
- **Mode:** always `dev_mode=true` on first install (~$1/mo). Full stack is
  a later upgrade.
- **Bedrock model:** Haiku 4.5 for the chat feature unless the user asks for
  a different one. The CLI runs a Bedrock pre-flight before deploying chat
  and will exit cleanly with a console URL if the model isn't enabled in
  the user's region — see "When things go wrong" below for how to recover.

## The flow

### Step 1 — Verify prerequisites yourself (don't ask the user)

Run these silently and only bring results to the user if something is missing:

```bash
aws --version
node --version
python3 --version
docker --version
npx cdk --version || npm install -g aws-cdk
python3 -c "import yaml" 2>/dev/null || echo "install pyyaml, ideally in a virtualenv"
```

If Docker isn't running, instruct the user to start it. CDK bundling needs it.

Do not install the CDK runtime by hand. The CLI creates `.venv-cdk` in the
repo on first deploy, installs each stack's `cdk/requirements.txt` into it, and
puts it on PATH so `python3 app.py` in every cdk.json uses that interpreter.

`pyyaml` above is the CLI's own dependency and is unrelated to the CDK
runtime, which is never installed into the host interpreter.

The `aws-cdk-lib` / `constructs` packages are the Python CDK runtime: every
`cdk.json` runs `python3 app.py`, so they must be importable or the first
`cdk deploy` fails at synth with `ModuleNotFoundError: No module named
'aws_cdk'`. `python3 tokenburner.py install` installs each stack's
`cdk/requirements.txt` automatically, so this is only needed if you invoke
`cdk` by hand.

### Step 2 — Verify AWS credentials

```bash
aws sts get-caller-identity
aws configure get region
```

If no credentials are configured, tell the user to run `aws configure` and
paste their access key. Do not ask for credentials directly.

### Step 3 — Ask the user which features to include

Use AskUserQuestion. Read `features.yaml` so the list is authoritative. Offer
a multiSelect question like:

> Which features should be part of your tokenburner stack? You can always
> add more later.
>
> - [x] Token Drive — personal file storage on S3
> - [x] Token Chat — AI chat with streaming responses and conversation history
> - [x] Token Forums — threaded discussion board, S3-backed
> - [x] Token Agent — desktop agent + admin console for managing accounts

Tell the user: "Chat uses AWS Bedrock (Claude Haiku by default). The other
features don't make any AI calls." This is the only place `Claude` may be
mentioned — it's describing what the feature is, not branding the stack.

### Step 4 — Run install

The CLI now auto-seeds `.tokenburner.json` from the AWS CLI's existing
credentials, so you don't need to write the config file manually. Just run:

```bash
python3 tokenburner.py install --features drive chat forums agent
```

If you need to override the AWS profile or region, pass `--profile` and
`--region` flags. Substitute the feature list based on the user's selection
from step 3.

Realistic timing for a fresh-account install:
- Base stack: ~5 min (CloudFront + custom-resource Lambda)
- Drive: ~3 min
- Chat: ~6 min
- Forums: ~6-12 min (CloudFront eventual consistency varies)
- Agent: ~9 min (two Lambdas, IAM policies, two CloudFront distributions)
- **Total full install: ~25-35 min, mostly wall clock waiting on CloudFront**

Report progress honestly — don't pretend something is done when it isn't.

The CLI runs a Bedrock pre-flight before any feature deploys if `chat` is
in the install list. If the configured model isn't enabled in the user's
target region, install will exit early with a console URL for the user to
enable it. Walk them through that step before retrying.

### Step 5 — Hand off the dashboard URL

When install finishes the CLI prints the dashboard URL and the bootstrap
admin key. Surface the "open with key" link so the user can click through:

```
https://<dashboard>.cloudfront.net/?key=sk_...
```

Explain that:
- The key is cached at `~/.tokenburner/credentials` (mode 0600).
- Every feature card uses the same key.
- They can create additional keys with `cd base-stack && python3 manage_keys.py create "..."`.

### Step 6 — Next steps menu

Offer the user the follow-up options that make sense given what they
installed:

- **Custom domain** — `python3 tokenburner.py domain example.com` (prints
  instructions; not fully automated yet).
- **Google SSO** — `python3 tokenburner.py sso enable`.
- **Add a feature later** — re-run `install --features <new>`.
- **Tear it all down** — `python3 tokenburner.py destroy` asks for
  confirmation and removes everything.

## Things to not do

- Don't deploy the full-stack mode on first install. The idle cost is ~$80/mo
  vs ~$1/mo for dev mode.
- Don't push any commits unless the user explicitly asks.
- Don't create IAM users, S3 buckets, or DDB tables outside of the CDK
  stacks — all infrastructure is defined in code.
- Don't ask the user to copy/paste AWS credentials. Use the AWS CLI's
  existing config.
- Don't mention `Claude` outside of this file and the feature-selection
  menu description. The stack is brand-neutral — the "Agent" feature is
  deliberately named generically so any AI backend can run behind it.

## When things go wrong

### Chat pre-flight: "The Bedrock model X is not available in Y"

This is the most common new-user failure. AWS Bedrock requires explicit
model access approval per region per account, and a brand-new account
has nothing approved by default. The CLI catches this BEFORE deploying
chat and exits with a message like:

```
The Bedrock model `us.anthropic.claude-haiku-4-5-20251001-v1:0` is not
available in us-east-1.
Enable model access in the AWS console:
  https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess
Then re-run `python3 tokenburner.py install`.
```

Do this:

1. **Tell the user honestly that approval may not be one-click.** Anthropic
   models on a new AWS account often require filling out a short use-case
   form. For Haiku 4.5 the approval is usually instant. For Opus models
   it can take hours.
2. **Walk them through the console.** Open the URL from the error message,
   click "Modify model access" (or "Manage model access"), find the row
   for **Claude Haiku 4.5** (matching the model id printed in the error —
   it's the row labeled "Anthropic / Claude Haiku 4.5"), check the box,
   submit any use-case form that appears, save.
3. **After approval, re-deploy just chat — not the whole install.** The
   base stack and other features are already up. Run:
   ```bash
   python3 tokenburner.py deploy chat
   ```
   This is idempotent and only takes ~6 minutes.
4. **If the user wants to skip Bedrock entirely**, you can install
   without chat:
   ```bash
   python3 tokenburner.py install --features drive forums agent
   ```
   They can add chat later by enabling the model and running
   `python3 tokenburner.py deploy chat`.

### Bedrock not available in the chosen region

A few AWS regions don't offer Bedrock at all (some GovCloud and opt-in
regions). The CLI prints a WARNING and continues — chat will deploy but
return 500 on the first message. If this happens, suggest the user
re-install in `us-east-1`, `us-west-2`, or another well-supported
commercial region:

```bash
python3 tokenburner.py destroy
python3 tokenburner.py install --region us-east-1
```

### Other gotchas

- **CloudFront takes time.** If the dashboard returns 403 right after
  install, wait ~60 seconds and try again.
- **DDB tables from a prior install** are RETAIN — if you destroy and
  reinstall, the new stack will collide. Delete the tables first:
  `aws dynamodb delete-table --table-name tokenburner-<name>`.
- **Stack bucket name collision.** S3 bucket names are globally unique.
  If `tokenburner-forums-<account>` already exists in a different account,
  the deploy will fail. Rename by editing forums/cdk/stack.py.

## Files in this repo

```
stack/
├── CLAUDE.md              # this file
├── README.md              # user-facing intro
├── tokenburner.md         # architecture + conventions
├── features.yaml          # the authoritative feature list
├── tokenburner.py         # real CLI (install, status, deploy, destroy, ...)
├── base-stack/
│   ├── cdk/               # base stack (DDB, S3, dashboard, bootstrap key)
│   ├── dashboard/         # the dashboard Flask+Lambda app
│   └── manage_keys.py     # API key management CLI
├── product-template/      # reference pattern for building a new feature
├── patterns/              # ai-chat, static-spa, background-job
├── website/               # tokenburner.ai landing site scaffolding
└── context/               # legacy context loader (for AI-driven workflows)
```
