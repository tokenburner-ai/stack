# Tokenburner Stack — install guide for Claude

You are helping the user install the tokenburner stack into their AWS account.
The goal is that from a fresh clone of this repo the user gets a working
dashboard URL with working feature cards in under ten minutes, without ever
opening a CDK file.

## Decisions Claude makes on behalf of the user

- **Region:** `us-west-2` by default unless the user has a strong preference.
- **Mode:** always `dev_mode=true` on first install (~$1/mo). Full stack is
  a later upgrade.
- **Bedrock model:** Haiku 4.5 for the chat feature unless the user asks for
  a different one.

## The flow

### Step 1 — Verify prerequisites yourself (don't ask the user)

Run these silently and only bring results to the user if something is missing:

```bash
aws --version
node --version
python3 --version
docker --version
npx cdk --version || npm install -g aws-cdk
python3 -c "import yaml" 2>/dev/null || pip install pyyaml --break-system-packages
```

If Docker isn't running, instruct the user to start it. CDK bundling needs it.

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

### Step 4 — Initialize config and install

If `.tokenburner.json` doesn't exist, write it directly with the profile,
region, and account ID you discovered in step 2. Do not use interactive
prompts. Then:

```bash
python3 tokenburner.py install --features drive chat forums agent
```

Substitute the feature list based on the user's selection from step 3.

Deploys take ~3 min (base) + ~5 min per feature. Report progress honestly —
don't pretend something is done when it isn't.

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

- **CloudFront takes time.** If the dashboard returns 403 right after
  install, wait ~60 seconds and try again.
- **DDB tables from a prior install** are RETAIN — if you destroy and
  reinstall, the new stack will collide. Delete the tables first:
  `aws dynamodb delete-table --table-name tokenburner-<name>`.
- **Bedrock model not enabled.** If chat 500s with "AccessDeniedException",
  the user needs to enable the model in the Bedrock console (one-click).
  Surface that clearly.
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
