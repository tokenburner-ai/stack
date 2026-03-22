# [Product Name] — Project Context

Brief description of what this product does.

## Quick Start

### Cloud (AWS)

```bash
cd cdk
pip install -r requirements.txt
cdk deploy tokenburner-[product-name]
```

### Local (Docker Compose)

```bash
docker compose up --build -d      # build + start
docker compose down                # stop
docker compose logs web -f         # tail logs
docker compose exec db psql -U tokenburner  # connect to postgres
```

URL: http://localhost:8080

## Architecture

```
[Describe your system here — containers, services, data flow]
```

## File Map

```
[product-name]/
├── app/
│   ├── main.py          # Flask application
│   ├── db.py            # Database connection pool
│   └── migrate.py       # Migration runner
├── migrations/
│   └── 001_initial.sql  # Baseline schema
├── static/
│   └── index.html       # Frontend
├── cdk/
│   ├── app.py           # CDK entry point
│   ├── stack.py         # Product stack (Fargate, ALB rule, DNS)
│   ├── cdk.json         # CDK config (product_name, subdomain)
│   └── requirements.txt # CDK dependencies
├── Dockerfile
├── docker-compose.yml   # Local development
├── requirements.txt     # Python dependencies
└── tokenburner.md       # This file
```

## Database

| Table | Purpose | Row Count |
|-------|---------|-----------|
| schema_migrations | Migration tracking | - |

Next migration: **002**

## Authentication

[Describe auth: API keys, user login, or both]

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| DATABASE_URL | (local only) | PostgreSQL connection string |
| DB_SECRET_JSON | (cloud, from Secrets Manager) | JSON with host/port/username/password |
| SECRET_KEY | change-me-in-production | Flask session secret |
| AWS_REGION | us-west-2 | AWS SDK region |
| PRODUCT_NAME | my-product | Product identifier |

## Common Tasks

**Add a migration:**
```bash
# Create migrations/002_add_something.sql
# Restart the service — migrations run on startup
```

**Deploy to cloud:**
```bash
cd cdk && cdk deploy
```

**Tear down:**
```bash
cd cdk && cdk destroy
```

## What's Built

- [ ] [List what's working]

## What's Not Built Yet

- [ ] [List what's planned]
