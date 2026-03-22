# Patterns

Reusable infrastructure and application patterns for tokenburner products.

## static-spa/
S3 + CloudFront static site with SPA routing. Use for frontends, dashboards, marketing sites.
- `cdk/stack.py` — Full CDK stack (S3, CloudFront, Route53)

## ai-chat/
Bedrock-powered AI chat with SSE streaming and conversation persistence.
- `app/chat.py` — Flask Blueprint, drop into any product
- `cdk_snippet.py` — DynamoDB + S3 resources to add to your CDK stack

## background-job/
Lambda function for event-driven processing with Aurora database access.
- `stack.py` — Full CDK stack (Lambda, VPC, Secrets Manager, optional API Gateway + EventBridge triggers)
- `handler.py` — Lambda entry point template
