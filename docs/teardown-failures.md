# Tokenburner teardown failures

This document explains why `tokenburner destroy` can fail mid-teardown, how the pieces depend on each other, and how to recover.

## Symptoms you may see

### 1. Agent stack: `TierBasic` / IAM managed policy delete failed

```
DELETE_FAILED | AWS::IAM::ManagedPolicy | TierBasic
Cannot delete a policy attached to entities.
```

### 2. Base stack: export still in use

```
Delete canceled. Cannot delete export tokenburner-api-keys-table-name
as it is in use by tokenburner-agent.
```

### 3. Retained S3 buckets after “successful” destroy

Feature stacks such as **forums** and **drive** set `RemovalPolicy.RETAIN` on their S3 buckets. After `cdk destroy`, buckets like `tokenburner-forums-<account>-<region>` or `tokendrive-files-<account>-<region>` remain. Versioned buckets need all object versions deleted before `aws s3 rb` succeeds.

### 4. Retained DynamoDB tables after “successful” destroy

Stacks are gone in CloudFormation, but tables such as `tokenburner-api-keys` still exist and block a clean redeploy.

### 5. Retained CloudWatch log groups after “successful” destroy

Lambda auto-creates a log group (`/aws/lambda/<function-name>`) the first time each function runs. These live **outside** the CDK stacks, so `cdk destroy` never removes them. After a teardown, log groups like `/aws/lambda/tokenburner-agent-admin` or `/aws/lambda/tokenburner-drive` remain and accumulate across install/destroy cycles. Low cost, but they clutter the account and are `tokenburner-*` / `tokenburner-*` leftovers.

---

## Root cause: agent IAM users outlive the stack

The **agent** feature (`features/agent`) creates two managed IAM policies in CDK:

- `tokenburner-agent-tier-basic-<region>` (`TierBasic`)
- `tokenburner-agent-tier-pro-<region>` (`TierPro`)

When an admin creates an account via the agent API, the stack:

1. Creates an IAM user at path `/tokenburner-agent/` (e.g. `tokenburner-agent-matteo`)
2. **Attaches** the tier managed policy to that user

Those attachments are **outside** CloudFormation’s normal resource graph. On destroy, CloudFormation tries to delete `TierBasic` while it is still attached to one or more users → **DELETE_FAILED**.

While `tokenburner-agent` is stuck (or still deleting), it continues to **import** exports from `tokenburner-base` (e.g. `tokenburner-api-keys-table-name`). The base stack cannot finish deletion until the agent stack is fully gone.

### Secondary issue: RETAIN on DynamoDB

Several tables use `RemovalPolicy.RETAIN` in CDK (api-keys, feature-registry, agent accounts/context). They are **intentionally** kept after stack destroy so data survives upgrades. A full account cleanup must delete them explicitly.

---

## Fixed workflow (CLI)

As of the teardown fix PR, `tokenburner destroy` handles the common case automatically:

| Step | What happens |
|------|----------------|
| Agent pre-destroy | Detach tier policies, delete access keys, delete `/tokenburner-agent/` users |
| Feature stacks | `cdk destroy` with retry + CloudFormation fallback on `DELETE_FAILED` |
| Base stack | `cdk destroy -c dev_mode=true` after all features are gone |
| `--purge-retained` | Empties and deletes retained S3 buckets (`tokenburner-*`, `tokenburner-*`, or `ManagedBy=tokenburner` tag), deletes retained DynamoDB tables, deletes retained CloudWatch log groups (`/aws/lambda/tokenburner-*`, `/aws/lambda/tokenburner-*`), removes `~/.tokenburner/credentials` |

### Full clean teardown

```bash
cd tokenburner-stack
printf 'destroy\n' | python3 tokenburner.py destroy --purge-retained
```

### Destroy only the agent feature

```bash
python3 tokenburner.py destroy agent
```

### Destroy agent + purge tables later

```bash
python3 tokenburner.py destroy agent --purge-retained
```

### Product stack (if you deployed `product-template`)

Destroyed automatically on full `destroy`, or explicitly:

```bash
python3 tokenburner.py destroy product
```

---

## Manual recovery (if CLI is unavailable)

1. List agent IAM users:
   ```bash
   aws iam list-users --path-prefix /tokenburner-agent/
   ```
2. For each user, detach `tokenburner-agent-tier-basic-*` and `tokenburner-agent-tier-pro-*`, delete access keys, delete the user.
3. Retry agent stack delete:
   ```bash
   cd features/agent/cdk && cdk destroy tokenburner-agent --force
   ```
4. Destroy base:
   ```bash
   cd base-stack/cdk && cdk destroy tokenburner-base --force -c dev_mode=true
   ```
5. Optionally delete retained buckets and tables:
   ```bash
   python3 tokenburner.py destroy --purge-retained
   ```
   Or manually empty versioned S3 objects then `aws s3 rb s3://tokenburner-forums-...`.

---

## CDK bootstrap role warnings

You may see:

```
current credentials could not be used to assume
arn:aws:iam::...:role/cdk-hnb659fds-deploy-role-...
```

This is common when using account root or a user that does not assume the CDK deploy role. Destroy often still succeeds. To silence it, configure credentials that can assume the bootstrap roles, or continue with admin credentials.

---

## Related files

- `tokenburner.py` — `cleanup_agent_iam_users`, `destroy_stack`, `purge_retained_resources`, `delete_s3_bucket`, `purge_log_groups`
- `features/agent/cdk/stack.py` — `TierBasic` / `TierPro` policies
- `features/agent/app/admin_api.py` — creates users and attaches policies
- `context/destroy.md` — AI assistant playbook for destroy
