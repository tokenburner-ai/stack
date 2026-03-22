# Tokenburner Stack — Project Context

The shared foundation for all tokenburner products. Fork this, describe what you want to build, and let your AI assistant generate a production SaaS.

## Philosophy

**Burn first, refine later.**

This stack is designed for agentic development. You start in the cloud, spend tokens and money freely to get something real deployed fast, then optimize once it's working. The most expensive part of building software is *not building it*. A $20 cloud bill and a few thousand AI tokens is cheaper than a week of planning.

The workflow:
1. Set up your AWS account (15 minutes)
2. Point your AI assistant at this repo
3. Describe what you want to build
4. The AI deploys infrastructure, writes code, iterates until it works
5. You have a live product — then you can optimize, go local, cut costs

You can always back off to local development later. But getting something real running in the cloud first means you're refining a working product, not speculating about one.

## AWS Account Setup

Before your AI assistant can build anything, you need these enabled in your AWS account. This is the one manual step — everything after this is agentic.

### Prerequisites

1. **AWS Account** with admin access
2. **AWS CLI v2** installed and configured (`aws configure`)
3. **AWS CDK** installed (`npm install -g aws-cdk`)
4. **Python 3.12+** installed
5. **Docker** installed (for CDK asset bundling)

### Account Discovery

After configuring the AWS CLI, have your AI assistant run the discovery commands below. This audits your account so the stack can reuse existing infrastructure and give you specific guidance on what's missing.

**Run all of these — the AI assistant will interpret the results:**

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

At idle with no traffic, the full stack costs roughly:

| Resource | Idle Cost | Notes |
|----------|-----------|-------|
| Aurora Serverless v2 (0.5 ACU min) | ~$22/mo | Scales to zero paused after 5 min inactivity |
| ALB | ~$16/mo | Fixed cost, shared across all products |
| ECS Fargate (1 task, 256 CPU) | ~$8/mo | Per running service |
| Route53 hosted zone | $0.50/mo | Per domain |
| CloudWatch Logs | ~$1/mo | Minimal at low volume |
| S3, DynamoDB, Secrets Manager | < $1/mo | Pay-per-request at low scale |
| **Total idle baseline** | **~$48/mo** | For the full platform with one product running |

Bedrock tokens are pay-per-use: ~$3/M input tokens, ~$15/M output tokens (Sonnet). A heavy development day might cost $5-15 in tokens. This is intentional — you're trading money for velocity.

**To cut costs later:**
- Pause Aurora when not in use (scales to zero)
- Develop locally with Docker Compose against a local Postgres
- Switch to Haiku for production AI features
- Tear down dev stacks when not actively building

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Route53 (DNS)                            │
│                    *.your-domain.com                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                   ┌────────▼────────┐
                   │   ACM (TLS)     │
                   │ Wildcard cert   │
                   └────────┬────────┘
                            │
              ┌─────────────▼─────────────────┐
              │   Application Load Balancer    │
              │   (shared, host-header routing)│
              └──┬──────────┬──────────┬──────┘
                 │          │          │
        ┌────────▼───┐ ┌───▼────┐ ┌───▼────────┐
        │ Product A  │ │Product │ │  Product C  │
        │ (Fargate)  │ │   B    │ │  (Fargate)  │
        │            │ │(Fargate│ │             │
        └─────┬──────┘ └───┬───┘ └──────┬──────┘
              │            │             │
              └────────────┼─────────────┘
                           │
              ┌────────────▼────────────┐
              │   Aurora PostgreSQL      │
              │   Serverless v2         │
              │   (shared or per-product)│
              └─────────────────────────┘

        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ DynamoDB │  │    S3    │  │ Bedrock  │
        │ (keys,   │  │ (files,  │  │ (AI      │
        │ sessions,│  │  assets, │  │  features)│
        │ config)  │  │  uploads)│  │          │
        └──────────┘  └──────────┘  └──────────┘
```

### Base Stack (deploys once)

The foundation that all products share. Deployed as a single CDK stack.

```
base-stack/
├── cdk/
│   ├── app.py              # CDK app entry point
│   ├── stack.py            # Base stack definition
│   ├── cdk.json            # CDK config
│   └── requirements.txt    # CDK dependencies
└── tokenburner.md          # This file
```

**Resources created:**

| Resource | Purpose | Shared? |
|----------|---------|---------|
| VPC (2 AZs, public + private subnets) | Networking foundation | Yes — all products |
| Application Load Balancer | HTTPS ingress, host-header routing | Yes — all products |
| ECS Cluster | Fargate task host | Yes — all products |
| Route53 Hosted Zone | DNS management | Yes — all products |
| ACM Wildcard Certificate | TLS termination | Yes — all products |
| DynamoDB table (api-keys) | Cross-service API key auth | Yes — all products |
| Aurora PostgreSQL Serverless v2 | Primary database | Shared or per-product |
| Secrets Manager (db credentials) | Database connection secrets | Per Aurora cluster |
| CloudWatch Log Group | Centralized logging | Per product |

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

Each product is an independent CDK stack that imports base resources.

```
my-product/
├── app/
│   ├── main.py             # Flask application
│   ├── db.py               # Database connection pool
│   └── migrate.py          # Migration runner
├── migrations/
│   └── 001_initial.sql     # Schema
├── static/
│   └── index.html          # Frontend
├── cdk/
│   ├── app.py              # CDK app entry point
│   ├── stack.py            # Product stack definition
│   ├── cdk.json            # CDK config
│   └── requirements.txt    # CDK dependencies
├── Dockerfile              # Container image
├── requirements.txt        # Python dependencies
└── tokenburner.md          # Product context file
```

**A product stack creates:**
- ECS Fargate service (task definition, security group, ALB target group)
- ALB listener rule (host-header routing: `product.your-domain.com`)
- Route53 A record (alias to ALB)
- Database schema (via migration runner on startup)
- S3 bucket (if product needs file storage)
- DynamoDB table (if product needs key-value storage)
- Lambda functions (if product needs background jobs)
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

PostgreSQL everywhere.

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

Two patterns depending on product needs:

### API Key Auth (service-to-service)

- Keys stored in shared DynamoDB table
- Passed via `X-API-Key` header
- Validated by each service independently
- Good for: APIs, webhooks, machine clients

### User Auth (human users)

- Users table in PostgreSQL
- Password hashing with werkzeug scrypt (or bcrypt)
- Flask session cookies
- Good for: web apps, dashboards, admin panels

## Deployment

### Deploy Base Stack (once)

```bash
cd base-stack/cdk
pip install -r requirements.txt
cdk deploy tokenburner-base
```

### Deploy a Product

```bash
cd my-product/cdk
pip install -r requirements.txt
cdk deploy my-product-stack
```

### Tear Down a Product (without affecting others)

```bash
cd my-product/cdk
cdk destroy my-product-stack
```

### Tear Down Everything

```bash
# Destroy products first, then base
cd my-product/cdk && cdk destroy my-product-stack
cd base-stack/cdk && cdk destroy tokenburner-base
```

## Environment Variables

Products use environment variables for configuration. In cloud, these come from the CDK stack (Fargate task definition + Secrets Manager). Locally, from `.env` or Docker Compose.

| Variable | Source | Purpose |
|----------|--------|---------|
| DATABASE_URL | Secrets Manager → Fargate env | PostgreSQL connection string |
| AWS_REGION | Fargate default | Region for AWS SDK calls |
| BEDROCK_MODEL | Fargate env | LLM model ID for AI features |
| API_KEYS_TABLE | CDK export | DynamoDB table name for API keys |
| S3_BUCKET | CDK export | Product-specific S3 bucket |
| LOG_LEVEL | Fargate env | Python logging level (default: INFO) |

## File Structure (this repo)

```
stack/
├── base-stack/
│   └── cdk/
│       ├── app.py           # CDK app entry
│       ├── stack.py         # Base stack (VPC, ALB, ECS, Aurora, Route53)
│       ├── cdk.json
│       └── requirements.txt
├── product-template/
│   ├── app/
│   │   ├── main.py          # Flask app template
│   │   ├── db.py            # Database connection template
│   │   └── migrate.py       # Migration runner template
│   ├── migrations/
│   │   └── 001_initial.sql  # Baseline migration
│   ├── static/
│   │   └── index.html       # Starter frontend
│   ├── cdk/
│   │   ├── app.py           # Product CDK app entry
│   │   ├── stack.py         # Product stack template
│   │   ├── cdk.json
│   │   └── requirements.txt
│   ├── Dockerfile
│   ├── requirements.txt
│   └── tokenburner.md       # Context file template
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

- [ ] This context file (tokenburner.md)
- [ ] Base stack CDK (VPC, ALB, ECS, Aurora, Route53, DynamoDB, Secrets Manager)
- [ ] Product template (Flask app, migrations, Dockerfile, CDK stack)
- [ ] Static SPA pattern
- [ ] AI chat pattern
- [ ] Background job pattern

## What's Not Built Yet

- [ ] CI/CD pipeline template (GitHub Actions)
- [ ] Monitoring / alerting templates (CloudWatch dashboards)
- [ ] Cost optimization guide (when and how to go local)
- [ ] Multi-region deployment
- [ ] Custom domain setup automation
