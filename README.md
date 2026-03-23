# Token Stack

Deploy a production SaaS into your AWS account in 7 minutes.
Then tell your AI assistant what to build.

## How it works

Fork this repo. Run `tokenburner deploy`. You get a live HTTPS endpoint with authentication, a database, Swagger API docs, and a dashboard — all running on your own AWS account. Then point any AI coding assistant at the repo and describe what you want to build. The context file keeps the AI aligned across sessions.

## Architecture

### Dev Mode (default — $0.42/mo)

```
                    ┌──────────────────────────────────────────────┐
                    │                  CloudFront                   │
 Browser ──HTTPS──▶ │              (CDN + HTTPS)                   │
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │              Lambda Function                  │
                    │         (Python 3.12 / Flask)                 │
                    │                                              │
                    │  ┌─────────┐  ┌──────────┐  ┌────────────┐  │
                    │  │ Routes  │  │ Swagger  │  │    Auth    │  │
                    │  │ main.py │  │  /docs   │  │  API Keys  │  │
                    │  └─────────┘  └──────────┘  └────────────┘  │
                    └──────┬──────────────┬───────────────┬────────┘
                           │              │               │
              ┌────────────▼──┐  ┌────────▼────┐  ┌──────▼──────┐
              │  SQLite-on-S3 │  │  DynamoDB   │  │   Secrets   │
              │  (database)   │  │ (API keys)  │  │   Manager   │
              │               │  │             │  │             │
              │  + branching  │  │  free tier  │  │  $0.40/mo   │
              │  + snapshots  │  │  $0.00/mo   │  │             │
              │  $0.01/mo     │  │             │  │             │
              └───────────────┘  └─────────────┘  └─────────────┘
```

### Full Stack (upgrade path — ~$71/mo)

```
                    ┌──────────────────────────────────────────────┐
                    │               ALB (Load Balancer)             │
 Browser ──HTTPS──▶ │              + ACM Certificate                │
                    └──────────────────┬───────────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────────┐
                    │              ECS Fargate                      │
                    │         (Python 3.12 / Gunicorn)             │
                    │         Auto-scaling containers              │
                    └──────┬──────────────┬───────────────┬────────┘
                           │              │               │
              ┌────────────▼──┐  ┌────────▼────┐  ┌──────▼──────┐
              │    Aurora      │  │  DynamoDB   │  │   Secrets   │
              │  PostgreSQL    │  │ (API keys)  │  │   Manager   │
              │  Serverless v2 │  │             │  │             │
              │               │  │             │  │             │
              └───────────────┘  └─────────────┘  └─────────────┘
```

The same application code runs on both. `db.py` auto-translates SQL between SQLite and Postgres. Switch with one config change when you're ready to scale.

## Tech Stack

| Layer | Dev Mode | Full Stack |
|-------|----------|------------|
| **Compute** | Lambda (Python 3.12) | ECS Fargate (Gunicorn) |
| **CDN / TLS** | CloudFront | ALB + ACM |
| **Database** | SQLite-on-S3 | Aurora PostgreSQL Serverless v2 |
| **Auth** | DynamoDB API keys + Google OAuth | Same |
| **Secrets** | AWS Secrets Manager | Same |
| **IaC** | AWS CDK (Python) | Same |
| **API Docs** | Swagger UI (auto-generated from docstrings) | Same |
| **AI Context** | `tokenburner.md` — keeps any AI assistant aligned | Same |

### Key Design Decisions

- **Dual-mode database** — `db.py` speaks both SQLite and Postgres. Write SQL once, it runs on either. Dev on SQLite-on-S3 for free, upgrade to Aurora when traffic demands it.
- **AI-native** — The `tokenburner.md` context file is the product definition. It tells your AI assistant the schema, conventions, deployment target, and what's already built. Works with Claude, ChatGPT, Copilot, or any coding assistant.
- **Context swap** — Save and restore entire product definitions (routes, schema, static files, database) via S3 snapshots. Switch between products in ~52 seconds.
- **OAS3 docstrings** — Write OpenAPI 3.0 specs inline in Python docstrings. Swagger UI generates automatically. No separate spec file to maintain.
- **Zero-cost default** — Lambda free tier covers 1M requests/month. S3 costs pennies. You pay $0.40/mo for Secrets Manager and nothing else until real traffic arrives.

## What it costs

| Resource | Dev Mode | Full Stack |
|---|---|---|
| Compute | $0.00 (Lambda free tier) | ~$30 (Fargate) |
| CDN / TLS | $0.00 (CloudFront free tier) | ~$18 (ALB) |
| Database | $0.01 (S3) | ~$15 (Aurora Serverless) |
| Auth | $0.00 (DynamoDB free tier) | $0.00 |
| Secrets | $0.40 | $0.40 |
| NAT Gateway | — | ~$8 |
| **Total** | **$0.42/mo** | **~$71/mo** |

## Get started

```bash
git clone https://github.com/tokenburner-ai/stack
cd stack
tokenburner deploy
```

After deploy completes (~7 min first time, ~25 sec updates):
1. Visit your CloudFront URL
2. Open `/docs` for Swagger API docs
3. Use the generated API key to authenticate
4. Point your AI assistant at `tokenburner.md` and start building

## What's inside

```
stack/
├── tokenburner.md              # AI context — the product definition
├── tokenburner.py              # CLI: deploy, status, destroy, extend, swap
├── context/                    # Sub-contexts for each CLI command
│   ├── deploy.md               # Deploy guide + verification steps
│   ├── destroy.md              # Safe teardown with DynamoDB cleanup
│   ├── extend-api.md           # Adding routes + OAS3 docstrings
│   ├── setup-domain.md         # Custom domain via Route53 / Cloudflare
│   ├── upgrade-neon.md         # SQLite → Postgres migration path
│   └── swap-context.md         # Save/restore product definitions
├── base-stack/                 # Shared infra CDK
│   └── cdk/                    # DynamoDB, S3, Secrets Manager
├── product-template/           # Your application
│   ├── app/
│   │   ├── main.py             # Flask routes + Swagger docstrings
│   │   ├── db.py               # Dual-mode: SQLite-on-S3 / Postgres
│   │   ├── auth.py             # API keys (DynamoDB) + Google OAuth
│   │   ├── migrate.py          # Auto-run SQL migrations on deploy
│   │   └── context_swap.py     # Save/load product snapshots via S3
│   ├── migrations/             # SQL schema (auto-translates per DB mode)
│   ├── static/                 # Frontend (login SPA, dashboard)
│   └── cdk/                    # Lambda+CloudFront or Fargate+ALB
├── patterns/                   # Drop-in feature patterns
│   ├── static-spa/             # Static site on CloudFront
│   ├── ai-chat/                # Bedrock AI chat with SSE streaming
│   └── background-job/         # Async task processing
└── website-template/           # Marketing site on CloudFront
```

## Patterns

Drop-in features you can add to any Token Stack product:

| Pattern | What it adds |
|---------|-------------|
| **static-spa** | CloudFront distribution for a frontend SPA |
| **ai-chat** | Bedrock-powered AI chat with SSE streaming |
| **background-job** | Async task queue with Lambda workers |

## Roadmap

- [ ] `tokenburner` CLI as pip-installable package
- [ ] CI/CD pipeline template (GitHub Actions)
- [ ] Monitoring + alerting templates (CloudWatch)
- [ ] Template generator (scaffold new products from CLI)
- [ ] Domain setup automation
- [ ] Neon Postgres upgrade path (alternative to Aurora)

## Links

- [tokenburner.ai](https://tokenburner.ai) — Project site
- [Token Stack](https://tokenburner.ai/stack) — Product page
- [API Preview](https://tokenburner.ai/api-docs) — See what you get before deploying
