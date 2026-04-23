# Add Drive to the Tokenburner Stack

This context file tells your AI assistant how to wire the Token Drive into an existing
tokenburner base stack deployment so the drive is available at `/drive` on the same
CloudFront domain — no second distribution, no second domain.

## Pre-requisites

- `tokenburner-base` stack is deployed (see `context/deploy.md`)
- You have the `tokenburner-ai/drive` repo available locally:

```bash
git clone https://github.com/tokenburner-ai/drive.git ~/tb/drive
```

## What gets deployed

| Resource | Name | Incremental cost |
|----------|------|-----------------|
| Lambda | `tokenburner-drive` | $0/mo idle |
| S3 bucket | `tokendrive-files-{account}` | ~$0.023/GB/mo |
| DynamoDB | `tokendrive-index` | $0/mo (free tier) |
| CloudFront behavior | `/drive` and `/drive/*` | $0 (added to existing distribution) |

No new CloudFront distribution is created. The drive rides the existing one.

## Step 1 — Deploy the Drive stack

```bash
cd ~/tb/drive/cdk
pip install -r requirements.txt

AWS_PROFILE=tokenburner \
  CDK_DEFAULT_ACCOUNT=$(AWS_PROFILE=tokenburner aws sts get-caller-identity --query Account --output text) \
  CDK_DEFAULT_REGION=us-west-2 \
  npx cdk deploy tokenburner-drive --require-approval never
```

Note the `DriveFunctionUrl` output — you'll need it in Step 2.

## Step 2 — Add /drive behavior to the base stack CloudFront

The base stack's CloudFront distribution needs two new behaviors:
- `/drive` → drive Lambda function URL
- `/drive/*` → drive Lambda function URL

Ask your AI assistant to add these behaviors to `~/tb/stack-dev/base-stack/cdk/stack.py`,
passing the drive Lambda function URL as an origin:

*"Add CloudFront behaviors for /drive and /drive/* pointing to the drive Lambda function URL
[paste DriveFunctionUrl here] in the tokenburner base stack"*

Then redeploy the base stack:

```bash
cd ~/tb/stack-dev/base-stack/cdk

AWS_PROFILE=tokenburner \
  CDK_DEFAULT_ACCOUNT=$(AWS_PROFILE=tokenburner aws sts get-caller-identity --query Account --output text) \
  CDK_DEFAULT_REGION=us-west-2 \
  npx cdk deploy tokenburner-base --require-approval never
```

## Step 3 — Set your Drive API key

```bash
AWS_PROFILE=tokenburner aws lambda update-function-configuration \
  --function-name tokenburner-drive \
  --environment "Variables={
    DRIVE_BUCKET=tokendrive-files-YOUR_ACCOUNT_ID,
    DRIVE_TABLE=tokendrive-index,
    DRIVE_API_KEY=your-secret-key-here
  }"
```

Generate a key: `python3 -c "import uuid; print(uuid.uuid4())"`

## Step 4 — Verify

Open `https://YOUR_CLOUDFRONT_DOMAIN/drive` in a browser. You should see the key gate.
Paste your API key to enter the drive.

The main landing page at `/` has a Drive card in the Tools section that links here.

## Seed sample files (optional)

```bash
cd ~/tb/drive
AWS_PROFILE=tokenburner python3 seed.py
```

Uploads README.md/pdf/xlsx/docx to the drive root so you have something to click on.
Delete from the UI whenever you like.

## Path prefix note

The drive Flask app serves all routes under `/` by default. When mounted behind
CloudFront at `/drive`, the `X-Forwarded-Prefix` header is set to `/drive` and
the drive handles it transparently — no code changes needed.

## Options

Once the drive is running, see `~/tb/drive/CONTEXT.md` for next steps:
custom domain, Google OAuth, Dropbox import, storage tiering, read-only sharing.

## Next products

The same pattern applies to Chat and Forum:
- `tokenburner-ai/chat` → mount at `/chat`, add a Chat card to the Tools section
- `tokenburner-ai/forum` → mount at `/forum`, add a Forum card to the Tools section

Each gets its own Lambda + data store, shares the CloudFront distribution.
