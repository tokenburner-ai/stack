# Destroy — Tokenburner Context

This context is loaded by `tokenburner destroy`. Follow every step in order.

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

## Step 1: List What Will Be Destroyed

List all tokenburner stacks and their resources:

```bash
AWS_PROFILE=<profile> aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[?starts_with(StackName,`tokenburner-`)].StackName' --output text
```

For each stack, list resources:

```bash
AWS_PROFILE=<profile> aws cloudformation list-stack-resources --stack-name <stack> \
  --query 'StackResourceSummaries[].{Type:ResourceType,Id:LogicalResourceId}' --output table
```

Present a clear summary of what will be destroyed:

```
The following tokenburner resources will be DESTROYED:

tokenburner-<product_name>:
  - Lambda function (tokenburner-<product_name>)
  - CloudFront distribution
  - IAM role + policy
  - Lambda function URL

tokenburner-base:
  - DynamoDB table (tokenburner-api-keys) — ALL API KEYS WILL BE LOST (has RETAIN policy, must delete manually after stack destroy)
  - S3 bucket (tokenburner-db-snapshots-<account>) — ALL DATABASE SNAPSHOTS WILL BE DELETED
  - Secrets Manager secret (tokenburner/google-oauth)

Resources NOT affected:
  - CDKToolkit (bootstrap stack, reusable)
  - Any non-tokenburner stacks
```

## Step 2: Confirm Destruction

**Ask the user explicitly:** "This will destroy all tokenburner resources including API keys and database snapshots. Type 'destroy' to confirm."

Do NOT proceed without the exact word "destroy". This is irreversible.

## Step 3: Destroy Product Stack First

Product stacks depend on base stack exports. Destroy them first.

```bash
cd product-template/cdk
AWS_PROFILE=<profile> cdk destroy --force -c dev_mode=true -c product_name=<product_name>
```

Wait for completion. Verify:

```bash
AWS_PROFILE=<profile> aws cloudformation describe-stacks --stack-name tokenburner-<product_name> 2>&1
# Should return "does not exist"
```

## Step 4: Destroy Base Stack

```bash
cd base-stack/cdk
AWS_PROFILE=<profile> cdk destroy --force -c dev_mode=true
```

Wait for completion. Verify:

```bash
AWS_PROFILE=<profile> aws cloudformation describe-stacks --stack-name tokenburner-base 2>&1
# Should return "does not exist"
```

## Step 5: Clean Up Retained Resources

The DynamoDB API keys table has a RETAIN removal policy and survives `cdk destroy`.

Check if it still exists:

```bash
AWS_PROFILE=<profile> aws dynamodb describe-table --table-name tokenburner-api-keys \
  --query 'Table.{Name:TableName,Items:ItemCount,Status:TableStatus}' --output table 2>&1
```

If the table exists, **ask the user:**

```
The DynamoDB API keys table (tokenburner-api-keys) was retained after stack destroy.
This table contains your API keys. If you delete it, all keys will be lost and
you'll need to create new ones on the next deploy.

Delete the API keys table? [y/N]
```

Only delete if the user confirms with "y" or "yes":

```bash
AWS_PROFILE=<profile> aws dynamodb delete-table --table-name tokenburner-api-keys 2>&1
```

If the user says no, note that the table will remain and may cause a conflict on the next `cdk deploy`. The deploy context handles this — it will detect the existing table and reuse it.

## Step 6: Verify Clean

```bash
AWS_PROFILE=<profile> aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[?starts_with(StackName,`tokenburner-`)].StackName' --output text
```

Should return empty. Present:

```
All tokenburner resources destroyed.

Remaining stacks (not touched):
  CDKToolkit
  <any other stacks>

To redeploy: run `tokenburner deploy`
```
