# Deploy — Tokenburner Context

This context is loaded by `tokenburner deploy`. Follow every step in order.

## Step 0: Confirm Environment

Read `.tokenburner.json` from the repo root. Then verify:

```bash
AWS_PROFILE=<profile> aws sts get-caller-identity --output json
```

Present to user:
```
Account:  <account_id>
Profile:  <profile>
Region:   <region>
Product:  <product_name>
```

Ask: "Deploy to this account? [Y/n]" — do NOT proceed without confirmation.

## Step 1: Deploy Base Stack

```bash
cd base-stack/cdk
pip install -r requirements.txt --quiet
AWS_PROFILE=<profile> cdk deploy --require-approval never -c dev_mode=true
```

Verify: `AWS_PROFILE=<profile> aws cloudformation describe-stacks --stack-name tokenburner-base --query 'Stacks[0].StackStatus'` should return `CREATE_COMPLETE` or `UPDATE_COMPLETE`.

## Step 2: Create API Key

```bash
cd base-stack
AWS_PROFILE=<profile> python3 manage_keys.py create "dev-admin" --permissions read write
```

Save the `sk_...` key — you'll need it for verification and the user needs it to log in.

## Step 3: Deploy Product Stack

```bash
cd product-template/cdk
pip install -r requirements.txt --quiet
AWS_PROFILE=<profile> cdk deploy --require-approval never -c dev_mode=true -c product_name=<product_name>
```

Extract the CloudFront URL from the stack outputs (`AppUrl`).

## Step 4: Verification (9 checks)

Run ALL checks yourself. Do not ask the user to run them.

```bash
URL="https://<cloudfront-domain>"
KEY="<api-key>"

# 1. Health check
curl -s $URL/health

# 2. Users API (authenticated)
curl -s $URL/api/users -H "Authorization: Bearer $KEY"

# 3. Accounts API (authenticated)
curl -s $URL/api/accounts -H "Authorization: Bearer $KEY"

# 4. Roles API (authenticated)
curl -s $URL/api/roles -H "Authorization: Bearer $KEY"

# 5. Auth enforcement (should return 401)
curl -s -o /dev/null -w "%{http_code}" $URL/api/users

# 6. Frontend loads
curl -s $URL/ | head -3

# 7. Smoke test writes
curl -s -X POST $URL/api/accounts \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test Inc", "slug": "smoke-test", "plan": "free"}'

curl -s -X POST $URL/api/roles \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"name": "tester", "description": "Smoke test role", "permissions": "read"}'

curl -s -X POST $URL/api/users \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test User", "email": "smoke@test.com", "account_id": 2, "role_id": 4}'

curl -s -X PUT $URL/api/accounts/2 \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"plan": "pro"}'

curl -s $URL/api/accounts -H "Authorization: Bearer $KEY"

# 8. Swagger UI loads
curl -s $URL/api-docs | grep -o '<title>.*</title>'

# 9. OpenAPI spec is valid
curl -s $URL/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'swagger' not in d; print(f'OAS {d[\"openapi\"]} — {len(d[\"paths\"])} paths')"
```

## Step 5: Cost Breakdown

List actual resources and present costs:

```bash
AWS_PROFILE=<profile> aws cloudformation list-stack-resources --stack-name tokenburner-base \
  --query 'StackResourceSummaries[].{Type:ResourceType,Id:LogicalResourceId}' --output table
AWS_PROFILE=<profile> aws cloudformation list-stack-resources --stack-name tokenburner-<product_name> \
  --query 'StackResourceSummaries[].{Type:ResourceType,Id:LogicalResourceId}' --output table
```

Present cost table:

| Stack | Resource | Cost |
|-------|----------|------|
| base | DynamoDB (on-demand, minimal reads) | ~$0.00/mo |
| base | S3 bucket (SQLite snapshots, <1 MB) | ~$0.01/mo |
| base | Secrets Manager (1 secret) | $0.40/mo |
| product | Lambda (free tier: 1M req/mo) | $0.00/mo |
| product | CloudFront (free tier: 1TB/mo) | $0.00/mo |
| product | IAM | $0.00/mo |
| **Total** | | **~$0.42/mo** |

## Step 6: Present to User

This is the user's first "wow" moment. Make it count.

```
Your app is live. Here's everything you need:

App URL:  https://<cloudfront-domain>
API Key:  <api-key>
Swagger:  https://<cloudfront-domain>/api-docs

Open the URL in your browser, paste the API key, and you'll see the
mock login with 3 demo users. Click "API Docs" for interactive Swagger UI.

Deployment:
  Base stack (dev mode):     ~1 min
  Create API key:            < 1 min
  Product (Lambda + CF):     ~5 min
  Total:                     ~7 min

Verification (all 9 checks pass):
  /health             → {"db_mode":"sqlite","status":"ok"}
  /api/users          → 3 seed users
  /api/accounts       → 1 demo account
  /api/roles          → 3 roles
  Unauth request      → 401
  /                   → SPA loads
  CRUD smoke test     → create + update all 201/200
  /api-docs           → Swagger UI loads
  /openapi.json       → valid OAS 3.0.3

Monthly cost: ~$0.42/mo
```
