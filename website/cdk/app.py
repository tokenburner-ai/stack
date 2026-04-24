#!/usr/bin/env python3
"""Website CDK app — static site on CloudFront, with optional custom domain."""

import os
import aws_cdk as cdk
from stack import WebsiteStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
)

product_name = app.node.try_get_context("product_name") or "my-product"
domain_name = app.node.try_get_context("domain_name")  # e.g., "myproduct.com" or None
subdomain = app.node.try_get_context("subdomain") or "www"  # e.g., "www" or "@" for apex
drive_lambda_url = app.node.try_get_context("drive_lambda_url")

WebsiteStack(
    app,
    f"tokenburner-{product_name}-website",
    env=env,
    product_name=product_name,
    domain_name=domain_name,
    subdomain=subdomain,
    drive_lambda_url=drive_lambda_url,
)

app.synth()
