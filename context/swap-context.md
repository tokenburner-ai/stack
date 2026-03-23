# Context Swap — Switch Product Definitions via S3

Swap between entirely different product APIs using saved contexts.
Each context captures: routes (`app/main.py`), schema (`migrations/`), frontend (`static/`), context file (`tokenburner.md`), and database state. Same CloudFront URL, completely different product.

## Prerequisites

- Base stack deployed (provides S3 bucket)
- Product deployed at least once
- `context_swap.py` in the product root

## Commands

```bash
# Save current product state
python context_swap.py save <name> --description "what this context is"

# List all saved contexts
python context_swap.py list

# See what would change
python context_swap.py diff <name>

# Switch to a different context (replaces local files + live database)
python context_swap.py load <name>

# Delete a saved context
python context_swap.py delete <name>
```

## Workflow

### 1. Save your starting point

Before experimenting, always save the current state:

```bash
python context_swap.py save baseline -d "Starter template with accounts, users, roles"
```

### 2. Build something new

Tell your AI assistant to modify the product — add new tables, routes, business logic. The AI updates `main.py`, adds migrations, modifies `tokenburner.md`.

### 3. Save the new version

```bash
python context_swap.py save inventory-tracker -d "Product catalog with SKUs, stock levels, reorder alerts"
```

### 4. Swap between them

```bash
# Go back to baseline
python context_swap.py load baseline

# Redeploy (same URL, different API)
# CDK deploy or tokenburner deploy

# Try the other one
python context_swap.py load inventory-tracker
# Redeploy again — now it's the inventory tracker
```

### 5. Diff before loading

```bash
python context_swap.py diff inventory-tracker
```

Shows unified diff of every file that would change.

## What Gets Saved

| File | Purpose |
|------|---------|
| `tokenburner.md` | Product definition (the AI reads this) |
| `app/main.py` | Routes, business logic, Swagger docs |
| `migrations/*.sql` | Database schema |
| `static/*` | Frontend files |
| `dev.sqlite` | Live database state (copied from S3) |

## What Happens on Load

1. All product files are replaced with the saved versions
2. Migrations not in the saved context are **deleted** (clean swap)
3. The live SQLite database in S3 is replaced with the saved snapshot
4. You review with `git diff`, then redeploy

## S3 Layout

```
s3://<bucket>/<product>/contexts/
  <name>/
    manifest.json        # metadata: name, description, timestamp, file list
    tokenburner.md
    app/main.py
    migrations/001_*.sql
    migrations/002_*.sql
    static/index.html
    dev.sqlite
```

## Key Points

- **Same URL**: After swapping and redeploying, the CloudFront URL serves the new API
- **Database included**: The swap restores the database state too — schema + data
- **Non-destructive locally**: Files are overwritten but nothing is committed — `git diff` shows everything, `git checkout .` reverts
- **Additive migrations**: If a new context has more migrations than the database, they run on next deploy. If fewer, the database is replaced from the snapshot.
- **Auth unchanged**: API keys live in DynamoDB (separate from the product database), so the same key works across context swaps

## Example: Two-Product Demo

```bash
# Start with the default template
python context_swap.py save default -d "Accounts, users, roles, emails CRUD"

# Tell AI: "Build a task tracker with projects and tasks"
# AI modifies main.py, adds 003_tasks.sql migration
# Test it, then save:
python context_swap.py save task-tracker -d "Projects and tasks with priority and assignment"

# Now swap between them:
python context_swap.py load default     # accounts API
python context_swap.py load task-tracker # tasks API

# Each swap + redeploy takes ~50 seconds total
```

## Timing (tested)

| Step | Time |
|------|------|
| `context_swap.py load <name>` | ~2 seconds |
| CDK redeploy (Lambda update) | ~50 seconds |
| **Total swap time** | **~52 seconds** |

## Size Guardrail

Contexts are capped at **50 MB** by default. The `save` command will refuse to save if total file size exceeds this limit. This prevents accidental inclusion of large files (data dumps, binaries, node_modules) that would bloat S3 and slow down swaps.

Override with `--max-size-mb 100` if needed.

## Environment Variables

| Variable | Source | Purpose |
|----------|--------|---------|
| `S3_DB_BUCKET` | Base stack export | S3 bucket for contexts + database |
| `PRODUCT_NAME` | `.tokenburner.json` | Namespace in S3 |
| `AWS_PROFILE` | `.tokenburner.json` | AWS credentials |
