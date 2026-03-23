# Status — Tokenburner Context

This context is loaded by `tokenburner status`. Follow every step in order.

## Step 0: Confirm Environment

Read `.tokenburner.json` from the repo root. Then verify:

```bash
AWS_PROFILE=<profile> aws sts get-caller-identity --output json
```

Present:
```
Account:  <account_id>
Profile:  <profile>
Region:   <region>
Product:  <product_name>
```

## Step 1: List Stacks

```bash
AWS_PROFILE=<profile> aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[].{Name:StackName,Status:StackStatus}' --output table
```

Identify tokenburner stacks (prefixed with `tokenburner-`). Note any non-tokenburner stacks separately.

## Step 2: List Resources Per Stack

For each tokenburner stack:

```bash
AWS_PROFILE=<profile> aws cloudformation list-stack-resources --stack-name <stack-name> \
  --query 'StackResourceSummaries[].{Type:ResourceType,Id:LogicalResourceId,Status:ResourceStatus}' --output table
```

## Step 3: Health Check

If a product stack exists, hit the health endpoint:

```bash
# Get CloudFront URL from stack outputs
AWS_PROFILE=<profile> aws cloudformation describe-stacks --stack-name tokenburner-<product_name> \
  --query 'Stacks[0].Outputs[?OutputKey==`AppUrl`].OutputValue' --output text

curl -s https://<cloudfront-domain>/health
```

## Step 4: API Key Status

```bash
AWS_PROFILE=<profile> aws dynamodb scan --table-name tokenburner-api-keys \
  --query 'Items[*].{key_id:key_id.S,name:name.S,active:active.BOOL}' --output table
```

## Step 5: Cost Breakdown

Present the cost table based on actual resources found:

| Stack | Resource | Cost |
|-------|----------|------|
| base | DynamoDB (on-demand, minimal reads) | ~$0.00/mo |
| base | S3 bucket (SQLite snapshots) | ~$0.01/mo |
| base | Secrets Manager (per secret) | $0.40/mo |
| product | Lambda (free tier) | $0.00/mo |
| product | CloudFront (free tier) | $0.00/mo |
| **Total** | | **~$0.42/mo** |

Adjust based on what's actually deployed (e.g., if no product stack, omit product costs).

## Step 6: Present Summary

```
Tokenburner Status — <account_id> (<profile>)

Stacks:
  tokenburner-base     <status>   (DynamoDB, S3, Secrets Manager)
  tokenburner-<name>   <status>   (Lambda, CloudFront)

Health:   <health response or "no product deployed">
API Keys: <count> keys (<active> active)
Cost:     ~$X.XX/mo

App URL:  https://<cloudfront-domain>
Swagger:  https://<cloudfront-domain>/api-docs
```
