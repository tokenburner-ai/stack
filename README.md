# Tokenburner Stack

A low-cost, install-and-forget AWS stack. Clone it, point your AI coding
assistant at it, and in under ten minutes you have a dashboard URL in your
own AWS account with one card per installed feature:

- **Drive** — personal file storage on S3
- **Chat** — AI chat with streaming responses and conversation history
- **Forums** — threaded discussion board, S3-backed
- **Agent** — admin console for managing accounts, access keys, and shared context

Everything runs in **dev mode** by default — one Lambda + CloudFront per
feature, DynamoDB on-demand, S3 on-demand. Idle cost is ~$1/mo for the whole
platform.

## Install

You need an AWS account and the AWS CLI configured (`aws configure`). Then:

```bash
git clone https://github.com/tokenburner-ai/stack.git
cd stack
```

Open the repo in any AI coding assistant that reads `CLAUDE.md`. It will:

1. Check prerequisites (Node.js, Python, Docker, CDK).
2. Verify your AWS credentials.
3. Ask which features you want.
4. Deploy the base stack and each feature.
5. Hand you a dashboard URL and an admin API key.

If you'd rather run the CLI directly:

```bash
pip install pyyaml
python3 tokenburner.py install
```

## What you get

```
                           ┌──────────────────────────────────────┐
User → CloudFront (HTTPS) →│ Dashboard Lambda  (one card/feature) │
                           └──────────────────────────────────────┘
                                          │
                                          ▼
                           ┌──────────────────────────────────────┐
                           │ Feature Registry DDB   API Keys DDB  │
                           └──────────────────────────────────────┘
                                          ▲
                 ┌────────────────────────┼────────────────────────┐
                 │                        │                        │
         Drive Lambda             Chat Lambda              Agent Lambda
         + CF + S3 + DDB          + CF + Bedrock + DDB    + CF + DDB
                 │                        │                        │
                 └──── self-register via custom resource ──────────┘
```

Each feature is its own CDK stack that imports from the base and writes one
row into the feature-registry table on deploy. The dashboard reads that
table and renders one card per registered feature.

## Costs

| Resource | Count | Idle cost |
|----------|-------|-----------|
| Lambda functions | 1 + N features | free tier |
| CloudFront distributions | 1 + N features | $0/mo idle |
| DynamoDB tables (on-demand) | 2 + feature tables | ~$0.30/mo |
| S3 buckets | 1 + feature buckets | ~$0.02/mo |
| Secrets Manager | 1 (OAuth placeholder) | ~$0.40/mo |

No VPC, no NAT Gateway, no ALB, no Aurora in dev mode. Full-stack mode
(Fargate + Aurora + ALB) is a supported upgrade path at ~$80/mo idle.

## Commands

```bash
python3 tokenburner.py install [--features a b c]   # base + features
python3 tokenburner.py status                        # what's deployed
python3 tokenburner.py deploy <feature>              # redeploy one
python3 tokenburner.py destroy [feature]             # remove one or all
python3 tokenburner.py domain <domain>               # attach a custom domain
python3 tokenburner.py sso enable                    # Google OAuth setup
```

## Adding your own feature

Each feature is an independent repo. The contract is:

- A CDK stack that imports two exports from the base stack:
  `tokenburner-api-keys-table-name` and
  `tokenburner-feature-registry-table-name`.
- An `AwsCustomResource` that writes one row to the feature registry on
  create/update, and deletes it on destroy. That row is what makes the card
  appear in the dashboard.
- An API gated by the shared `require_auth` decorator (see
  `base-stack/dashboard/app/auth.py`).

The simplest reference is [drive](https://github.com/tokenburner-ai/drive).
Copy its layout, rename, and add your feature to `features.yaml`.

## Architecture

See [`tokenburner.md`](./tokenburner.md) for the architecture document and
conventions. The short version: one base stack provides shared infrastructure
(API-key store, feature registry, dashboard CloudFront+Lambda, auto-minted
bootstrap admin key), and each feature is an independent CDK stack that
imports what it needs.

## License

MIT.
