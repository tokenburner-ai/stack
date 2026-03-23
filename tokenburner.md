# Tokenburner Stack — Project Context

The shared foundation for all tokenburner products. Fork this, describe what you want to build, and let your AI assistant generate a production SaaS.

## Philosophy

**Burn first, refine later.**

This stack is designed for agentic development. You start in the cloud, spend tokens and money freely to get something real deployed fast, then optimize once it's working. The most expensive part of building software is *not building it*. A $20 cloud bill and a few thousand AI tokens is cheaper than a week of planning.

The workflow:
1. Set up your AWS account (15 minutes)
2. Deploy the base stack in dev mode (`cdk deploy -c dev_mode=true`) — ~$1/mo
3. Deploy your product (`cdk deploy -c dev_mode=true -c product_name=my-product`) — $0/mo
4. You have a live HTTPS URL with a working API in minutes
5. Point your AI assistant at this repo, describe what you want to build
6. The AI writes code, deploys updates, iterates until it works
7. When ready for production, switch to full stack mode (~$80/mo)

Everything runs in the cloud from minute one. Dev mode uses Lambda + CloudFront + SQLite-on-S3 for near-zero cost. You can optionally run locally with Docker Compose, but the default dev flow is 100% cloud.

## AWS Account Setup

Before your AI assistant can build anything, you need these enabled in your AWS account. This is the one manual step — everything after this is agentic.

### Prerequisites

1. **AWS Account** with admin access
2. **AWS CLI v2** installed and configured (`aws configure`)
3. **Node.js 18+** installed (required by CDK) — `node --version`
4. **AWS CDK CLI** installed — `npm install -g aws-cdk` then verify with `cdk --version`
5. **Python 3.12+** installed — `python3 --version`
6. **Docker** installed (for CDK asset bundling and local development) — `docker --version`

**Quick prerequisite check** — run this before anything else:

```bash
# Verify all tools are installed
echo "--- Prerequisites Check ---"
node --version 2>/dev/null || echo "MISSING: Node.js — install from https://nodejs.org/ or: sudo apt install nodejs npm"
cdk --version 2>/dev/null || echo "MISSING: AWS CDK — run: npm install -g aws-cdk"
python3 --version 2>/dev/null || echo "MISSING: Python 3 — install from https://python.org/"
aws --version 2>/dev/null || echo "MISSING: AWS CLI — install from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
docker --version 2>/dev/null || echo "MISSING: Docker — install from https://docs.docker.com/get-docker/"
echo "--- End Check ---"
```

If anything says MISSING, install it before continuing. On Ubuntu/Debian:

```bash
# Node.js (via NodeSource for latest LTS)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Then CDK
npm install -g aws-cdk

# Python (usually pre-installed)
sudo apt install -y python3 python3-pip python3-venv

# AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install

# Docker
sudo apt install -y docker.io && sudo usermod -aG docker $USER
```

### Account Discovery

After configuring the AWS CLI, your AI assistant should run the prerequisite check and discovery commands below **autonomously** — do not ask the user to run them. The assistant should fix any missing tools, then audit the account and report what's ready vs. what needs action.

**AI assistant: run all of these yourself and interpret the results:**

```bash
# Identity — who am I and what account is this?
aws sts get-caller-identity
aws iam list-account-aliases

# Region — what region is configured?
aws configure get region

# Bedrock — are models enabled?
aws bedrock list-foundation-models --query 'modelSummaries[?true].{id:modelId,name:modelName,status:modelLifecycle.status}' --output table

# CDK — is the account bootstrapped?
aws cloudformation describe-stacks --stack-name CDKToolkit --query 'Stacks[0].{Status:StackStatus,Created:CreationTime}' --output table 2>/dev/null || echo "CDK NOT BOOTSTRAPPED"

# VPC — any existing VPCs beyond the default?
aws ec2 describe-vpcs --query 'Vpcs[].{VpcId:VpcId,Cidr:CidrBlock,Default:IsDefault,Name:Tags[?Key==`Name`]|[0].Value}' --output table

# Load Balancers — any existing ALBs we can share?
aws elbv2 describe-load-balancers --query 'LoadBalancers[].{Name:LoadBalancerName,DNS:DNSName,Scheme:Scheme,VpcId:VpcId,State:State.Code,Type:Type}' --output table 2>/dev/null || echo "NO LOAD BALANCERS"

# ECS — any existing clusters?
aws ecs list-clusters --output table 2>/dev/null || echo "NO ECS CLUSTERS"

# Route53 — any hosted zones / domains already configured?
aws route53 list-hosted-zones --query 'HostedZones[].{Name:Name,Id:Id,Records:ResourceRecordSetCount,Private:Config.PrivateZone}' --output table 2>/dev/null || echo "NO HOSTED ZONES"

# ACM — any existing TLS certificates?
aws acm list-certificates --query 'CertificateSummaryList[].{Domain:DomainName,Status:Status,Type:Type,InUse:InUseBy[0]}' --output table 2>/dev/null || echo "NO CERTIFICATES"
# Also check us-east-1 (required for CloudFront certs)
aws acm list-certificates --region us-east-1 --query 'CertificateSummaryList[].{Domain:DomainName,Status:Status,Type:Type}' --output table 2>/dev/null || echo "NO CERTIFICATES IN us-east-1"

# Aurora / RDS — any existing database clusters?
aws rds describe-db-clusters --query 'DBClusters[].{Cluster:DBClusterIdentifier,Engine:Engine,Status:Status,Endpoint:Endpoint,Serverless:ServerlessV2ScalingConfiguration}' --output table 2>/dev/null || echo "NO DB CLUSTERS"

# DynamoDB — any existing tables?
aws dynamodb list-tables --output table 2>/dev/null || echo "NO DYNAMODB TABLES"

# S3 — existing buckets (may contain useful assets or prior deployments)
aws s3 ls 2>/dev/null || echo "NO S3 BUCKETS"

# Secrets Manager — any existing secrets?
aws secretsmanager list-secrets --query 'SecretList[].{Name:Name,Description:Description}' --output table 2>/dev/null || echo "NO SECRETS"

# Lambda — any existing functions?
aws lambda list-functions --query 'Functions[].{Name:FunctionName,Runtime:Runtime,LastModified:LastModified}' --output table 2>/dev/null || echo "NO LAMBDA FUNCTIONS"

# Service Quotas — check Fargate and Bedrock limits
aws service-quotas get-service-quota --service-code fargate --quota-code L-3032A538 --query 'Quota.{Name:QuotaName,Value:Value}' --output table 2>/dev/null || echo "COULD NOT CHECK FARGATE QUOTA"

# IaC State — detect resources managed by Terraform, CloudFormation, or other tools
# Terraform state buckets (convention: name contains "terraform" or "tfstate")
aws s3 ls 2>/dev/null | grep -iE 'terraform|tfstate' || echo "NO TERRAFORM STATE BUCKETS FOUND"

# CloudFormation stacks — everything managed by CFN/CDK
aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query 'StackSummaries[].{Name:StackName,Status:StackStatus,Updated:LastUpdatedTime,Drift:DriftInformation.StackDriftStatus}' --output table 2>/dev/null || echo "NO CLOUDFORMATION STACKS"

# Check for Terraform resource tags on key infrastructure
aws ec2 describe-vpcs --query 'Vpcs[?Tags[?Key==`terraform`||Key==`tf:managed`||Key==`ManagedBy`||Key==`aws:cloudformation:stack-name`]].{VpcId:VpcId,Name:Tags[?Key==`Name`]|[0].Value,ManagedBy:Tags[?Key==`ManagedBy`||Key==`terraform`||Key==`aws:cloudformation:stack-name`]|[0].Value}' --output table 2>/dev/null
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null | tr '\t' '\n' | while read arn; do echo "--- $arn ---"; aws elbv2 describe-tags --resource-arns "$arn" --query 'TagDescriptions[].Tags[?Key==`ManagedBy`||Key==`terraform`||Key==`aws:cloudformation:stack-name`||Key==`aws:cloudformation:stack-id`]' --output table 2>/dev/null; done
aws rds describe-db-clusters --query 'DBClusters[].{Cluster:DBClusterIdentifier,Tags:TagList[?Key==`ManagedBy`||Key==`terraform`||Key==`aws:cloudformation:stack-name`]}' --output table 2>/dev/null
```

### Interpreting Discovery Results

The AI assistant should evaluate the results and tell you:

**Green (ready to go):**
- AWS CLI authenticated with admin access
- Bedrock models show as ACTIVE for your region
- CDK bootstrap stack exists and is CREATE_COMPLETE
- At least one hosted zone with a usable domain

**Yellow (can proceed, with adjustments):**
- Existing ALB found → base stack can import it instead of creating a new one (saves ~$16/mo)
- Existing ECS cluster found → base stack can share it
- Existing Aurora cluster found → products can use it instead of creating a new one (saves ~$22/mo)
- Existing VPC found → base stack can use it instead of creating a new one
- Existing wildcard cert found → base stack imports it instead of creating one
- Existing DynamoDB tables → check for naming conflicts before deploying

**Orange (managed infrastructure detected — proceed with caution):**

If discovery finds resources tagged with `ManagedBy`, `terraform`, `tf:managed`, or `aws:cloudformation:stack-name`, those resources are controlled by an IaC tool. This is critical to understand:

- **Terraform-managed resources**: If you modify these outside of Terraform (e.g., by importing into CDK or changing manually), the next `terraform apply` will revert or destroy your changes. The Terraform state file is the source of truth.
- **CloudFormation/CDK-managed resources**: Same risk — if another CDK stack owns a resource, deploying that stack could overwrite your modifications.
- **Pulumi, SAM, or other tools**: Same principle applies to any IaC tool with state management.

**What to do when managed resources are found:**
- **DO NOT import or modify** resources owned by another IaC tool
- **DO** create new resources alongside them (new ALB, new VPC, etc.) to avoid conflicts
- **DO** reference them read-only if needed (e.g., peer VPCs, share a hosted zone by zone ID)
- **DO** warn the user which resources are managed and by what tool
- If the user wants to share managed resources, they should add the tokenburner stack's resources through their existing IaC tool, not the other way around

The AI assistant should clearly report: "These resources exist but are managed by [Terraform/CDK/other]. I'll create new resources for tokenburner instead of touching these."

**Red (action needed before deploying):**
- No Bedrock model access → enable models in the console (see below)
- CDK not bootstrapped → run `cdk bootstrap` (see below)
- No admin permissions → need broader IAM access
- No hosted zone → stack will use ALB DNS (functional but no custom domain)

### Enable Bedrock Models

If discovery shows no Bedrock models, go to the [Bedrock Model Access console](https://console.aws.amazon.com/bedrock/home#/modelaccess) and request access to:
- At least one LLM family (check Bedrock pricing for current options and tiers)
- Enable in your primary region (us-west-2 recommended)

Model access approval is usually instant for on-demand.

### Bootstrap CDK

If discovery shows CDK is not bootstrapped, run once per account/region:

```bash
cdk bootstrap aws://ACCOUNT_ID/us-west-2
```

### Domain Setup

If discovery found existing hosted zones, the AI assistant should recommend which domain/subdomain to use (e.g., `apps.your-existing-domain.com`).

If no hosted zones exist and you have a domain:
1. Create a Route53 hosted zone for your domain
2. Point your registrar's nameservers to the Route53 NS records
3. Wait for DNS propagation (usually < 1 hour)

If you don't have a domain, the stack works fine with ALB-provided DNS (e.g., `tokenburner-alb-123456.us-west-2.elb.amazonaws.com`). You can add a custom domain later.

### Cost Expectations

**Dev mode** (SQLite-on-S3, no Aurora/NAT/ALB):

| Resource | Cost | Notes |
|----------|------|-------|
| S3, DynamoDB, Secrets Manager | < $1/mo | Pay-per-request, negligible at dev scale |
| Bedrock tokens | Pay-per-use | ~$3/M input, ~$15/M output (Sonnet) |
| **Total dev mode** | **~$1/mo** | Plus token costs during active development |

**Full stack** (production, all resources running):

| Resource | Idle Cost | Notes |
|----------|-----------|-------|
| NAT Gateway | ~$32/mo | Fixed cost, required for private subnet internet |
| Aurora Serverless v2 (0.5 ACU min) | ~$22/mo | Scales to zero when paused |
| ALB | ~$16/mo | Fixed cost, shared across all products |
| ECS Fargate (1 task, 256 CPU) | ~$8/mo | Per running service |
| Route53 hosted zone | $0.50/mo | Per domain |
| CloudWatch Logs, S3, DynamoDB | < $2/mo | Minimal at low volume |
| **Total idle baseline** | **~$80/mo** | For the full platform with one product running |

**Recommended workflow:**
1. Start in dev mode (SQLite-on-S3) — build your API, iterate on schemas (~$1/mo)
2. Switch to Neon free tier when you need real Postgres ($0/mo)
3. Deploy full stack when ready for production (~$80/mo)
4. Power down expensive resources when not actively testing (see below)

A heavy development day might cost $5-15 in Bedrock tokens. This is intentional — you're trading money for velocity.

**Power down** (stop paying for idle production resources):
- Stop Aurora cluster (`aws rds stop-db-cluster`)
- Delete NAT Gateway (recreate when needed)
- Scale ECS services to zero
- ALB is the hardest to avoid — consider tearing down between sessions

## Architecture

### Dev Mode (~$1/mo)

```
User → CloudFront (HTTPS) → Lambda (Flask app) → SQLite-on-S3
                                                → DynamoDB (API keys)
```

Three resources: Lambda serves your Flask app (API + static files), CloudFront provides HTTPS + caching, SQLite-on-S3 is your database. Deploy in minutes, iterate instantly, costs essentially nothing.

### Full Stack (~$80/mo, production)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Route53 (DNS)                            │
│                    *.your-domain.com                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────▼─────────────────┐
              │   Application Load Balancer    │
              │   (shared, host-header routing)│
              └──┬──────────┬──────────┬──────┘
                 │          │          │
        ┌────────▼───┐ ┌───▼────┐ ┌───▼────────┐
        │ Product A  │ │Product │ │  Product C  │
        │ (Fargate)  │ │   B    │ │  (Fargate)  │
        └─────┬──────┘ └───┬───┘ └──────┬──────┘
              │            │             │
              └────────────┼─────────────┘
                           │
              ┌────────────▼────────────┐
              │   Aurora PostgreSQL      │
              │   Serverless v2         │
              └─────────────────────────┘

        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ DynamoDB │  │    S3    │  │ Bedrock  │
        │ (keys,   │  │ (files,  │  │ (AI      │
        │ sessions,│  │  assets, │  │  features)│
        │ config)  │  │  uploads)│  │          │
        └──────────┘  └──────────┘  └──────────┘
```

### Base Stack (deploys once)

The foundation that all products share. Deployed as a single CDK stack with a `dev_mode` flag.

```
base-stack/
├── cdk/
│   ├── app.py              # CDK app entry point
│   ├── stack.py            # Base stack definition (dev_mode flag)
│   ├── cdk.json            # CDK config
│   └── requirements.txt    # CDK dependencies
├── manage_keys.py          # API key management CLI
└── tokenburner.md          # This file
```

**Dev mode resources** (`-c dev_mode=true`):

| Resource | Purpose | Cost |
|----------|---------|------|
| DynamoDB table (api-keys) | Cross-service API key auth | ~$0.10/mo |
| S3 bucket (db-snapshots) | SQLite databases + snapshots | ~$0.01/mo |
| Secrets Manager (OAuth) | Google OAuth credentials (placeholder) | ~$0.40/mo |

**Full stack resources** (no `dev_mode` flag):

| Resource | Purpose | Cost |
|----------|---------|------|
| All dev mode resources | (same) | ~$0.50/mo |
| VPC (2 AZs, public + private subnets) | Networking foundation | included |
| NAT Gateway | Private subnet internet access | ~$32/mo |
| Application Load Balancer | HTTPS ingress, host-header routing | ~$16/mo |
| ECS Cluster | Fargate task host | ~$1/mo |
| Aurora PostgreSQL Serverless v2 | Primary database | ~$22/mo |
| Route53 Hosted Zone | DNS management | $0.50/mo |
| ACM Wildcard Certificate | TLS termination | free |
| Secrets Manager (db credentials) | Database connection secrets | ~$0.40/mo |

**CloudFormation Exports** (consumed by product stacks):

```
tokenburner-vpc-id
tokenburner-public-subnets
tokenburner-private-subnets
tokenburner-alb-arn
tokenburner-alb-dns
tokenburner-alb-security-group
tokenburner-alb-https-listener-arn
tokenburner-ecs-cluster-name
tokenburner-ecs-cluster-arn
tokenburner-route53-zone-id
tokenburner-route53-zone-name
tokenburner-db-secret-arn
tokenburner-db-cluster-endpoint
tokenburner-api-keys-table-name
```

### Product Stack (one per product)

Each product is an independent CDK stack. In dev mode, it deploys as Lambda + CloudFront. In full stack mode, it deploys as Fargate + ALB.

```
my-product/
├── app/
│   ├── main.py             # Flask application
│   ├── db.py               # Database layer (Postgres or SQLite-on-S3)
│   ├── auth.py             # API key + Google OAuth auth
│   └── migrate.py          # Migration runner
├── migrations/
│   ├── 001_initial.sql     # Schema
│   └── 002_seed_data.sql   # Demo data
├── static/
│   └── index.html          # Frontend (mock login + dashboard)
├── cdk/
│   ├── app.py              # CDK app entry point (chooses dev or full stack)
│   ├── stack.py            # DevProductStack + ProductStack
│   ├── cdk.json            # CDK config
│   └── requirements.txt    # CDK dependencies
├── lambda_handler.py       # Lambda entry point (apig-wsgi)
├── Dockerfile              # Container image (for full stack)
├── requirements.txt        # Python dependencies
└── tokenburner.md          # Product context file
```

**Dev mode** (`-c dev_mode=true`): ~$0/mo (Lambda free tier)
- Lambda function (Flask app via apig-wsgi adapter)
- Lambda function URL (HTTPS endpoint)
- CloudFront distribution (CDN + nice URL)
- Uses SQLite-on-S3 from base stack's snapshots bucket
- Uses DynamoDB API keys from base stack

**Full stack mode**: ~$8/mo per product
- ECS Fargate service (task definition, security group, ALB target group)
- ALB listener rule (host-header routing: `product.your-domain.com`)
- Route53 A record (alias to ALB)
- Uses Aurora PostgreSQL from base stack
- CloudWatch log group

## Product Patterns

### Pattern: Web App (Fargate)

The default. A Flask app in a container, behind the shared ALB.

```
User → ALB (host-header) → Fargate Task → Aurora PostgreSQL
                                        → S3 (files)
                                        → DynamoDB (sessions)
```

- ECS Fargate: 256 CPU / 512 MB minimum (scales up)
- Gunicorn with 2+ workers
- Health check on `/health`
- ALB routes by host header (e.g., `app.tokenburner.ai`)
- Database migrations run on container startup

### Pattern: Static SPA (S3 + CloudFront)

For standalone frontends, dashboards, marketing sites.

```
User → CloudFront (CDN) → S3 Bucket (static files)
                        → API (separate Fargate service or Lambda)
```

- S3 bucket with static website hosting
- CloudFront distribution with cache optimization
- ACM certificate (us-east-1 for CloudFront)
- Route53 alias record
- SPA routing: 404 → index.html
- Deploys independently — just push files to S3

### Pattern: AI Chat (Bedrock + SSE)

For products with an AI assistant or chat feature.

```
User → ALB → Fargate Task → Bedrock (streaming)
                          → DynamoDB (conversation history)
                          → S3 (knowledge base / context)
```

- Flask endpoint with SSE (Server-Sent Events) streaming
- Bedrock converse_stream API for LLM calls
- DynamoDB table for conversation persistence
- S3 bucket for uploaded documents / knowledge base
- Lightweight Fargate task: 256 CPU / 512 MB

### Pattern: Background Job (Lambda)

For event-driven processing, webhooks, scheduled tasks.

```
Trigger (API GW / S3 / Schedule) → Lambda → Aurora (via RDS Proxy)
                                          → S3
                                          → DynamoDB
```

- Python 3.12 Lambda function
- API Gateway trigger for webhooks
- S3 event trigger for file processing
- EventBridge schedule for cron jobs
- RDS Proxy for database connections (avoids Lambda connection exhaustion)

## Database

PostgreSQL everywhere — but you don't need a Postgres server to start building.

### Dev Mode: SQLite-on-S3 (Zero Cost)

The product template's `db.py` supports two backends with the same API:

| Mode | Set | Cost | Use For |
|------|-----|------|---------|
| **SQLite-on-S3** | `S3_DB_BUCKET` | ~$0/mo | Building APIs, schema iteration, demos |
| **Postgres** | `DATABASE_URL` | $0-22/mo | Staging, production, complex queries |

**How it works**: Your database is a SQLite file stored in S3. Every write uploads the updated file. Every cold start downloads it. Same `query()`, `execute()`, `transact()` interface — your application code doesn't change.

```bash
# SQLite-on-S3 mode (zero cost)
S3_DB_BUCKET=tokenburner-db-snapshots S3_DB_KEY=myproduct/dev.sqlite python -m flask run

# Local Postgres (Docker Compose)
docker compose up -d   # DATABASE_URL set in docker-compose.yml

# Cloud Postgres (Neon free tier — real Postgres, scales to zero)
DATABASE_URL=postgresql://user:pass@ep-cool-name.us-west-2.aws.neon.tech/mydb python -m flask run

# Cloud Postgres (Aurora — production)
# DATABASE_URL from Secrets Manager, set by CDK automatically
```

**Caveats** (the AI assistant should tell users when they're outgrowing this):
- Single writer only — not safe for concurrent requests
- Adds ~200-500ms per write (S3 upload)
- SQLite doesn't support JSONB operators (`@>`, `?`), Postgres arrays, or some window functions
- Database file over ~50MB = noticeable latency on every write
- **When to upgrade**: any of these → switch to Neon (free, real Postgres) or Aurora

The AI assistant has these guardrails in context. It will proactively tell users: "You're outgrowing SQLite-on-S3 — here's how to switch to real Postgres in 60 seconds."

### Database Branching

Save and restore database states like git branches:

```bash
python db_branch.py save before-migration    # Snapshot current state
python db_branch.py save feature-x           # Save a feature branch
python db_branch.py list                     # See all snapshots
python db_branch.py restore before-migration # Roll back instantly
python db_branch.py delete old-snapshot      # Clean up
```

Snapshots are stored in S3 (`tokenburner-db-snapshots` bucket). Works with both SQLite and Postgres (via pg_dump). Switch between database states in seconds — no waiting for restores or reprovisioning.

**Optional upgrade: Neon** — If you want real Postgres for free, [Neon](https://neon.tech) offers a free tier with built-in database branching (a superset of db_branch). Just set `DATABASE_URL` to your Neon connection string. Same migrations, same app code, zero changes.

### Schema Conventions

```sql
-- Every table gets these columns
id SERIAL PRIMARY KEY,
created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

-- Use TIMESTAMPTZ, never TIMESTAMP
-- Use TEXT, never VARCHAR (PostgreSQL treats them identically)
-- Use JSONB for flexible/evolving fields
-- Foreign keys always have indexes
```

### Migrations

Numbered SQL files, run in order on startup:

```
migrations/
├── 001_initial.sql
├── 002_add_users.sql
├── 003_add_products.sql
```

- Tracked in a `schema_migrations` table
- Each migration runs in a transaction
- Migrations are append-only — never edit an applied migration
- Next migration number is always documented in the context file

### DynamoDB Usage

DynamoDB is for specific patterns, not general data:

| Use Case | Table Design |
|----------|-------------|
| API keys | Partition key: `api_key`, attributes: `owner`, `permissions`, `created_at` |
| Sessions | Partition key: `session_id`, TTL on `expires_at` |
| Conversations | Partition key: `conversation_id`, sort key: `message_id` |
| Config/flags | Partition key: `key`, attributes: `value`, `updated_at` |

Rule: if you need JOINs, aggregations, or complex queries, use PostgreSQL.

## Authentication

Two auth paths — every tokenburner product supports both out of the box.

### 1. API Keys (programmatic access)

For services, scripts, CI/CD, and machine clients.

- Key format: `sk_` + 32 hex characters (e.g., `sk_a1b2c3d4e5f6...`)
- Passed via `Authorization: Bearer sk_...`, `X-API-Key: sk_...`, or `?key=sk_...`
- Validated against the shared DynamoDB API keys table
- Supports permissions (`read`, `write`), environment scoping, and expiration

**DynamoDB API Keys Table Schema:**

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `key_id` | String (PK) | Yes | `sk_<32 hex>` — the key itself |
| `name` | String (GSI) | Yes | Human-readable name for lookup |
| `active` | Boolean | Yes | Enabled/disabled (default: true) |
| `permissions` | List | Yes | `["read"]` or `["read", "write"]` |
| `environments` | List | Yes | `["dev", "prd"]` or `["*"]` for all |
| `email` | String | No | Owner's email |
| `description` | String | No | Key purpose |
| `created_at` | String | Yes | ISO 8601 timestamp |
| `created_by` | String | Yes | Creator identity |
| `last_used_at` | String | Auto | Updated on each authentication |
| `expires_at` | String | No | Expiration (checked on auth) |

**Key management CLI:**

```bash
cd base-stack
python manage_keys.py list
python manage_keys.py create "My App" --email user@example.com
python manage_keys.py create "CI Pipeline" --permissions read write
python manage_keys.py revoke sk_abc123...
python manage_keys.py inspect sk_abc123...
```

**Validation flow in application code:**
1. Extract key from request (header or query param)
2. DynamoDB `GetItem` by `key_id`
3. Check `active`, check `expires_at`
4. Update `last_used_at` (fire-and-forget)
5. Return `Identity` object with name, permissions, environments

### 2. Google OAuth (human users)

For browser-based sign-in — dashboards, admin panels, web apps.

- Standard OAuth 2.0 authorization code flow
- Google client credentials stored in Secrets Manager (`tokenburner/google-oauth`)
- Flask session cookies after successful login
- Routes: `/auth/login`, `/auth/callback`, `/auth/logout`, `/auth/status`

**Google OAuth setup (one-time):**
1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create an OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URIs: `https://your-product.your-domain.com/auth/callback`
4. Store client_id and client_secret in Secrets Manager:
   ```bash
   aws secretsmanager put-secret-value \
     --secret-id tokenburner/google-oauth \
     --secret-string '{"client_id":"YOUR_ID","client_secret":"YOUR_SECRET"}'
   ```

### Auth decorators

```python
from auth import require_auth, require_write, get_identity

@app.route("/api/data")
@require_auth          # API key OR Google session
def get_data():
    identity = request.identity
    ...

@app.route("/api/data", methods=["POST"])
@require_write         # requires "write" permission
def create_data():
    ...
```

### API Documentation (Swagger)

Every product auto-generates OpenAPI docs:
- **Swagger UI**: `/docs` — interactive API explorer with auth
- **OpenAPI spec**: `/openapi.json` — machine-readable spec
- Powered by flasgger — docstrings become API documentation
- Both auth methods shown in Swagger UI (API key and Google OAuth)

## Deployment

### Deploy Base Stack (once)

```bash
cd base-stack/cdk
pip install -r requirements.txt

# Dev mode (~$1/mo — DynamoDB + S3 + Secrets Manager only)
cdk deploy -c dev_mode=true

# Full stack (~$71/mo — VPC, ALB, ECS, Aurora, NAT Gateway)
cdk deploy
```

### Create an API Key (after base stack deploy)

```bash
cd base-stack
python manage_keys.py create "dev-admin" --permissions read write
# Save the sk_... key — you'll need it to access your product's API
```

### Deploy a Product

```bash
cd my-product/cdk
pip install -r requirements.txt

# Dev mode ($0/mo — Lambda + CloudFront + SQLite-on-S3)
cdk deploy -c dev_mode=true -c product_name=my-product

# Full stack (~$8/mo — Fargate + ALB)
cdk deploy -c product_name=my-product -c subdomain=my-product
```

### Post-Deploy: Verify & Present to User

**AI assistant: after deploying the base stack + product, run these verification checks yourself and present the results to the user.** Do not ask the user to run them. The user's first experience should be seeing their working app.

```bash
# Extract the CloudFront URL and API key from deploy outputs
# Then run all 6 checks:

# 1. Health check
curl -s https://<cloudfront-domain>/health

# 2. Users API (authenticated)
curl -s https://<cloudfront-domain>/api/users -H "Authorization: Bearer <api-key>"

# 3. Accounts API (authenticated)
curl -s https://<cloudfront-domain>/api/accounts -H "Authorization: Bearer <api-key>"

# 4. Roles API (authenticated)
curl -s https://<cloudfront-domain>/api/roles -H "Authorization: Bearer <api-key>"

# 5. Auth enforcement (unauthenticated — should return 401)
curl -s -o /dev/null -w "%{http_code}" https://<cloudfront-domain>/api/users

# 6. Frontend loads (mock login SPA)
curl -s https://<cloudfront-domain>/ | head -3

# 7. Smoke test writes — verify CRUD actually works end-to-end
# Create an account
curl -s -X POST https://<cloudfront-domain>/api/accounts \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test Inc", "slug": "smoke-test", "plan": "free"}'

# Create a role
curl -s -X POST https://<cloudfront-domain>/api/roles \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "tester", "description": "Smoke test role", "permissions": "read"}'

# Create a user on the new account
curl -s -X POST https://<cloudfront-domain>/api/users \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test User", "email": "smoke@test.com", "account_id": 2, "role_id": 4}'

# Update the account
curl -s -X PUT https://<cloudfront-domain>/api/accounts/2 \
  -H "Authorization: Bearer <api-key>" \
  -H "Content-Type: application/json" \
  -d '{"plan": "pro"}'

# Verify the writes persisted
curl -s https://<cloudfront-domain>/api/accounts -H "Authorization: Bearer <api-key>"

# 8. Swagger UI loads
curl -s https://<cloudfront-domain>/api-docs | grep -o '<title>.*</title>'

# 9. OpenAPI spec is valid (no swagger/openapi conflict)
curl -s https://<cloudfront-domain>/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'swagger' not in d, 'swagger field present'; print(f'OAS {d[\"openapi\"]} — {len(d[\"paths\"])} paths')"
```

**Then present everything to the user like this:**

---

Your app is live. Here's everything you need:

**App URL:** `https://<cloudfront-domain>`
**API Key:** `<api-key>`

Open the URL in your browser, paste the API key, and you'll see the mock login with 3 demo users.

| Step | Time |
|------|------|
| Base stack deploy (dev mode) | ~1 min |
| Create API key | < 1 min |
| Product deploy (Lambda + CloudFront) | ~5 min |
| **Total** | **~7 min** |

**Verification (all 9 checks pass):**
- `/health` → `{"db_mode":"sqlite","status":"ok"}`
- `/api/users` → 3 seed users (admin, editor, viewer)
- `/api/accounts` → 1 demo account
- `/api/roles` → 3 roles with permissions
- Unauthenticated request → 401 (auth enforced)
- `/` → Mock login SPA loads
- CRUD smoke test → create account, role, user, update account — all return 201/200
- `/api-docs` → Swagger UI loads
- `/openapi.json` → valid OAS 3.0.3 spec, no swagger field

**Monthly cost estimate:** After verification, list the actual deployed resources and their costs:

```bash
# List resources in both stacks
AWS_PROFILE=tokenburner aws cloudformation list-stack-resources --stack-name tokenburner-base \
  --query 'StackResourceSummaries[].{Type:ResourceType,Id:LogicalResourceId}' --output table
AWS_PROFILE=tokenburner aws cloudformation list-stack-resources --stack-name tokenburner-<product_name> \
  --query 'StackResourceSummaries[].{Type:ResourceType,Id:LogicalResourceId}' --output table
```

Then present a cost breakdown like this:

| Stack | Resource | Cost |
|-------|----------|------|
| base | DynamoDB (on-demand, minimal reads) | ~$0.00/mo |
| base | S3 bucket (SQLite snapshots, <1 MB) | ~$0.01/mo |
| base | Secrets Manager (1 secret) | $0.40/mo |
| product | Lambda (free tier: 1M req/mo) | $0.00/mo |
| product | CloudFront (free tier: 1TB/mo) | $0.00/mo |
| product | IAM | $0.00/mo |
| **Total** | | **~$0.42/mo** |

Note: Secrets Manager is the only real cost. Lambda and CloudFront stay free at dev-mode traffic levels.

---

This is the user's first "wow" moment. Make it count — show them a working product, not a wall of terminal output.

### Extending the API

To add a new resource (e.g., "products"), follow this pattern:

**1. Create a migration** — `migrations/003_products.sql`

```sql
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
```

Note: Use SQLite-compatible syntax for dev mode. The `db.py` layer handles translation for Postgres.

**2. Add routes to `main.py`** following the existing CRUD pattern:

- `@require_auth` for GET (read), `@require_write` for POST/PUT (write)
- Return `jsonify(rows)` for lists, `jsonify(rows[0])` for single items
- POST returns 201, PUT returns 200, missing records return 404
- Use parameterized queries (`%s` placeholders) — `db.py` translates to `?` for SQLite

**3. Write OAS3 docstrings** — flasgger reads these to generate `/openapi.json` and Swagger UI automatically.

IMPORTANT: Use OpenAPI 3.0 format, NOT Swagger 2.0. The key differences:

```python
# GET with path parameter
@app.route("/api/products/<int:product_id>", methods=["GET"])
@require_auth
def get_product(product_id):
    """Get product by ID.
    ---
    tags: [Products]
    parameters:
      - name: product_id
        in: path
        required: true
        schema:
          type: integer          # OAS3: type is inside schema
    responses:
      200:
        description: Product object
      404:
        description: Not found
    """

# POST/PUT with JSON body
@app.route("/api/products", methods=["POST"])
@require_write
def create_product():
    """Create a product.
    ---
    tags: [Products]
    requestBody:                   # OAS3: NOT "parameters: in: body"
      required: true
      content:
        application/json:          # This tells Swagger UI to send Content-Type header
          schema:
            type: object
            required: [name, price, account_id]
            properties:
              name:
                type: string
              price:
                type: number
              account_id:
                type: integer
    responses:
      201:
        description: Created product
      400:
        description: Validation error
    """
```

Common mistakes to avoid:
- `parameters: in: body` is Swagger 2.0 — use `requestBody` for OAS3
- `type: integer` directly on a path param is Swagger 2.0 — wrap in `schema:`
- Missing `content: application/json:` causes 415 Unsupported Media Type in Swagger UI

**4. Deploy the update**

```bash
cd product-template/cdk
AWS_PROFILE=tokenburner cdk deploy -c dev_mode=true -c product_name=<name>
```

Lambda updates in ~25 seconds. New routes appear in Swagger UI automatically — no manual spec editing.

**5. Smoke test the new endpoints** — run POST/GET/PUT curls to verify before handing off to the user.

### Tear Down a Product (without affecting others)

```bash
cd my-product/cdk
cdk destroy -c dev_mode=true -c product_name=my-product
```

### Optional: Run Locally

You can also run the product locally with Docker Compose (uses Postgres):

```bash
cd my-product
docker compose up -d
# Visit http://localhost:8080
```

The same Flask app works in both environments. The `db.py` layer auto-detects whether to use Postgres (local/production) or SQLite-on-S3 (Lambda dev mode).

### Deploy a Website

```bash
# Without a domain (live instantly on CloudFront URL)
cd website/cdk
pip install -r requirements.txt
cdk deploy -c product_name=my-product

# With a custom domain
cdk deploy -c product_name=my-product -c domain_name=myproduct.com -c subdomain=www
```

See `website/README.md` for full domain setup guide (Route53, external registrars, adding a domain later).

### Tear Down Everything

Tokenburner only destroys resources it created. Resources that existed before tokenburner (VPCs, ALBs, clusters, databases passed in via `existing_*` context params) are **never touched** by `cdk destroy`. Only resources with the `ManagedBy: tokenburner` tag were created by the stack.

```bash
# Destroy products first, then base
cd my-product/cdk && cdk destroy my-product-stack
cd website/cdk && cdk destroy tokenburner-my-product-website
cd base-stack/cdk && cdk destroy tokenburner-base
```

**Safe to destroy:**
- Product stacks (Fargate services, ALB rules, DNS records, log groups)
- Website stacks (S3 buckets, CloudFront distributions, certs, DNS records)
- Base stack (VPC, ALB, ECS cluster, Aurora, DynamoDB — only if tokenburner created them)

**Never destroyed:**
- Resources imported via `existing_vpc_id`, `existing_alb_arn`, `existing_ecs_cluster_name`, `existing_db_cluster_id`
- Resources managed by other IaC tools (Terraform, other CDK stacks)
- Data in Aurora (removal policy = SNAPSHOT — a final snapshot is taken)
- DynamoDB API keys table (removal policy = RETAIN)

## Environment Variables

Products use environment variables for configuration. In cloud, these come from the CDK stack (Fargate task definition + Secrets Manager). Locally, from `.env` or Docker Compose.

| Variable | Source | Purpose |
|----------|--------|---------|
| DATABASE_URL | Secrets Manager → Fargate env | PostgreSQL connection string |
| DB_SECRET_JSON | Secrets Manager → Fargate secret | JSON with host/port/username/password |
| AWS_REGION | Fargate default | Region for AWS SDK calls |
| BEDROCK_MODEL | Fargate env | LLM model ID for AI features |
| API_KEYS_TABLE | CDK export | DynamoDB table name for API keys |
| GOOGLE_CLIENT_ID | Secrets Manager → Fargate secret | Google OAuth client ID |
| GOOGLE_CLIENT_SECRET | Secrets Manager → Fargate secret | Google OAuth client secret |
| SECRET_KEY | Fargate env | Flask session encryption key |
| S3_BUCKET | CDK export | Product-specific S3 bucket |
| LOG_LEVEL | Fargate env | Python logging level (default: INFO) |

## File Structure (this repo)

```
stack/
├── base-stack/
│   ├── cdk/
│   │   ├── app.py           # CDK app entry (reads dev_mode context)
│   │   ├── stack.py         # Base stack (dev: DynamoDB+S3+Secrets, full: +VPC+ALB+ECS+Aurora)
│   │   ├── cdk.json
│   │   └── requirements.txt
│   └── manage_keys.py       # API key management CLI (create, list, revoke, inspect)
├── product-template/
│   ├── app/
│   │   ├── main.py          # Flask app with Swagger docs (/docs, /openapi.json)
│   │   ├── auth.py          # Dual auth: API keys (DynamoDB) + Google OAuth
│   │   ├── db.py            # Dual-mode database (Postgres or SQLite-on-S3)
│   │   └── migrate.py       # Migration runner (works with both modes)
│   ├── migrations/
│   │   ├── 001_initial.sql  # Schema (accounts, users, roles, emails)
│   │   └── 002_seed_data.sql # Demo data (3 users, 3 roles, 1 account)
│   ├── static/
│   │   └── index.html       # Mock login SPA (API key → user picker → dashboard)
│   ├── cdk/
│   │   ├── app.py           # Product CDK app (chooses DevProductStack or ProductStack)
│   │   ├── stack.py         # Dev: Lambda+CloudFront, Full: Fargate+ALB
│   │   ├── cdk.json
│   │   └── requirements.txt
│   ├── lambda_handler.py    # Lambda entry point (apig-wsgi adapter for Flask)
│   ├── db_branch.py         # Database branching CLI (save/restore snapshots)
│   ├── Dockerfile           # Container image (for full stack mode)
│   ├── docker-compose.yml   # Local development (optional)
│   ├── requirements.txt     # Flask, flasgger, psycopg2, boto3, apig-wsgi
├── website/
│   ├── static/
│   │   ├── index.html       # Landing page (flame particles, dark theme)
│   │   └── style.css        # Responsive styles with tokenburner branding
│   ├── cdk/
│   │   ├── app.py           # CDK entry with domain_name/subdomain context
│   │   ├── stack.py         # S3 + CloudFront + optional Route53/ACM
│   │   ├── cdk.json
│   │   └── requirements.txt
│   └── README.md            # Domain setup guide (Route53, external, none)
├── patterns/
│   ├── static-spa/          # S3 + CloudFront pattern
│   ├── ai-chat/             # Bedrock + SSE pattern
│   └── background-job/      # Lambda pattern
└── tokenburner.md           # This file
```

## Creating a New Product

1. Copy `product-template/` to a new repo under `tokenburner-ai`
2. Rename and fill in `tokenburner.md` with your product's purpose
3. Point your AI assistant at the repo
4. Tell it what to build — it reads the context and generates the product
5. Deploy: `cd cdk && cdk deploy`
6. Iterate: describe changes, AI updates code + context file

The AI assistant handles:
- Writing application code (Flask routes, database queries, frontend)
- Writing CDK infrastructure (new resources, permissions, networking)
- Running migrations (generating SQL, updating schema docs)
- Updating the context file (keeping architecture docs in sync)

You handle:
- AWS account setup (one-time)
- Describing what you want built (in plain English)
- Reviewing and approving deployments
- Deciding when to optimize or go local

## What's Built

- [x] This context file (tokenburner.md)
- [x] Base stack CDK with dev_mode flag (dev: DynamoDB+S3+Secrets, full: +VPC+ALB+ECS+Aurora)
- [x] Product template with dual deployment (dev: Lambda+CloudFront, full: Fargate+ALB)
- [x] Dual-mode database (Postgres or SQLite-on-S3) with auto SQL translation
- [x] Database branching CLI (save/restore snapshots to S3)
- [x] API key management CLI (create, list, revoke, inspect)
- [x] Dual auth (DynamoDB API keys + Google OAuth)
- [x] Seed schema (accounts, users, roles, emails) with CRUD API
- [x] Mock login SPA (API key → user picker → dashboard)
- [x] Swagger/OpenAPI docs on every product (/docs)
- [x] Static SPA pattern (S3 + CloudFront)
- [x] AI chat pattern (Bedrock + SSE)
- [x] Background job pattern (Lambda)
- [x] Website template (flame particle landing page)

## What's Not Built Yet

- [ ] Auto-generate API key during base stack deploy
- [ ] CI/CD pipeline template (GitHub Actions)
- [ ] Monitoring / alerting templates (CloudWatch dashboards)
- [ ] Multi-region deployment
- [ ] Custom domain setup automation
- [ ] The storage product itself
