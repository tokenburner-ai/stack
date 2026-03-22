#!/usr/bin/env python3
"""Product CDK app — imports tokenburner base stack resources."""

import os
import aws_cdk as cdk
from stack import ProductStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
)

product_name = app.node.try_get_context("product_name") or "my-product"
subdomain = app.node.try_get_context("subdomain") or product_name

ProductStack(
    app,
    f"tokenburner-{product_name}",
    env=env,
    product_name=product_name,
    subdomain=subdomain,
)

app.synth()
