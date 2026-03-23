# Dogfooding Log

## Round 1 (Mar 22, 2026)

First end-to-end deployment as a new user.

### Issues Found & Fixed

**Issue 1: Node.js not listed as prerequisite** (FIXED)
- `cdk: command not found`. Prerequisites didn't mention Node.js.
- Fix: Added Node.js to prereqs, added quick check script with install commands.

**Issue 2: ALB dual-listener conflict without domain** (FIXED)
- `add_redirect(80→443)` + HTTP listener on port 80 = conflict. CloudFormation rolled back 35 resources.
- Fix: Only add redirect when certificate exists. HTTP-only path creates single listener.
- Collateral: orphaned DynamoDB table (RETAIN policy) needed manual cleanup.

**Issue 3: DynamoDB deprecation warning** (FIXED)
- `pointInTimeRecovery` deprecated → use `point_in_time_recovery_specification`.

**Issue 4: Node.js 18 EOL warnings** (cosmetic)
- CDK prints large banners. Recommend Node.js 20+ in docs.

**Issue 5: AI should run checks autonomously** (FIXED)
- Context now explicitly tells the AI to run prereq checks itself, not ask user.

**Issue 6: Cost table was wrong** (FIXED)
- NAT Gateway (~$32/mo) was missing from cost estimates. Real idle cost ~$71/mo, not $48/mo.
- Added dev mode cost section ($1/mo with SQLite-on-S3).

**Issue 7: No dev mode — full stack is expensive for exploring** (FIXED)
- Built SQLite-on-S3 mode: dual-mode db.py, auto Postgres→SQLite SQL translation.
- Built database branching: save/restore snapshots via S3.
- Built seed schema (accounts, users, emails, roles) with CRUD API + mock login UI.
- All API endpoints locked behind DynamoDB API keys from day one.

### Key Architecture Decisions from Round 1

1. **Base stack needs a dev_mode flag** — skip Aurora, NAT Gateway, and ALB when not needed. The $1/mo dev tier vs $71/mo full stack is a 70x difference.

2. **SQLite-on-S3 works** — tested migrations, CRUD, JOINs, aggregations, transactions. Auto-translates SERIAL→INTEGER, TIMESTAMPTZ→TEXT, now()→datetime('now'), %s→?. WAL checkpoint before S3 upload ensures integrity.

3. **Database branching works** — save v1, modify, save v2, restore v1 ✓, restore v2 ✓. Snapshots stored in S3 as .sqlite files with .meta.json.

4. **API keys stay in DynamoDB** — not in the SQLite dev database. DynamoDB is the production auth pattern from day one. ~$0.10/mo.

5. **ALB welcome page** — serves a mini branded HTML page (within 1024 byte limit) so users see something after deploy. Links to GitHub org.

6. **Website stack** — S3 + CloudFront, flame particle landing page. ~$0/mo at low traffic.

### What Needs to Change for Round 2

- [x] Add `dev_mode=true` context flag to base stack (skip Aurora, NAT Gateway, ALB)
- [x] Dev mode should only create: DynamoDB, Secrets Manager, S3 snapshot bucket
- [x] Full stack deploys everything (for when user is ready for production)
- [x] tokenburner.md should guide the user through dev mode first, full stack later
- [ ] The `manage_keys.py` create command should be part of the automated setup, not manual
- [x] Website is a separate step (not part of base stack)

### Round 1 Timeline

| Step | Time |
|------|------|
| Prereq check | 1 min |
| CDK bootstrap | < 1 min |
| Bedrock model access | Manual (console) |
| First deploy (failed) | 3 min |
| Bug fix + cleanup + redeploy | 11 min |
| Website deploy | 5.5 min |
| ALB welcome page update | 0.5 min |
| SQLite-on-S3 dev + test | 15 min |
| CRUD API + seed data + mock login | 20 min |
| **Total round 1** | **~57 min** |

---

## Round 2 (Mar 22, 2026)

Deploy from clean slate with dev_mode flag. Goal: working app in the cloud at ~$1/mo.

### Changes Made Before Round 2

1. **dev_mode flag in base stack** — `cdk deploy -c dev_mode=true` creates only DynamoDB + S3 + Secrets Manager. No VPC, ALB, ECS, Aurora, NAT Gateway.
2. **Lambda + CloudFront product deployment** — `DevProductStack` serves Flask app via Lambda function URL behind CloudFront. Same Flask app, same auth, same migrations — just serverless.
3. **apig-wsgi adapter** — bridges Flask (WSGI) to Lambda function URL events. `mangum` was ASGI-only and didn't work with Flask.

### Issues Found & Fixed

**Issue 8: AWS_DEFAULT_REGION is reserved by Lambda** (FIXED)
- Lambda runtime owns this env var. CDK throws `ValidationError` at synth.
- Fix: Removed it — Lambda already sets `AWS_REGION` automatically.

**Issue 9: mangum doesn't work with Flask** (FIXED)
- Flask is WSGI, mangum expects ASGI. Error: `Flask.__call__() takes 3 positional arguments but 4 were given`.
- Fix: Switched to `apig-wsgi` which is designed for WSGI apps on Lambda.

**Issue 10: Lambda migrations path wrong** (FIXED)
- `migrate.py` uses `os.path.dirname(__file__) + "/../migrations"`. In Lambda's flat bundle, this resolves to `/var/migrations` instead of `/var/task/migrations`.
- Fix: `lambda_handler.py` patches `migrate.MIGRATIONS_DIR` before importing the app.

### Round 2 Results

Everything works end-to-end:
- Base stack (dev mode): DynamoDB + S3 + Secrets Manager — deployed in **47 seconds**
- Product stack: Lambda + CloudFront — deployed in **5 minutes** (CloudFront creation is the bottleneck)
- Health: `{"db_mode":"sqlite","status":"ok"}`
- API: Full CRUD with DynamoDB auth + SQLite-on-S3 data
- Frontend: Mock login SPA served via CloudFront
- Subsequent code updates deploy in **25 seconds** (Lambda update only, CloudFront cached)

### Round 2 Timeline

| Step | Time |
|------|------|
| Prereq check | < 1 min |
| Account discovery | < 1 min |
| Base stack deploy (dev mode) | 47 sec |
| Product stack deploy (first, incl. CloudFront) | 5 min |
| Create API key | < 1 min |
| Fix Lambda issues (3 bugs) + redeploy | 5 min |
| End-to-end verification | 1 min |
| Context update | 5 min |
| **Total round 2** | **~14 min** |

### What Needs to Change for Round 3

- [ ] Auto-generate API key as part of base stack deploy (CDK custom resource or post-deploy script)
- [ ] tokenburner.md workflow should be: deploy base → deploy product → open CloudFront URL → enter API key → done
- [ ] Consider: should the AI auto-create the API key after deploying the base stack?
