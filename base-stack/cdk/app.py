#!/usr/bin/env python3
"""Tokenburner Base Stack — shared infrastructure for all products."""

import os
import aws_cdk as cdk
from stack import TokenburnerBaseStack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
)

# Context values — override via cdk.json, CLI, or environment
dev_mode = app.node.try_get_context("dev_mode") in (True, "true", "True", "1", "yes")
domain_name = app.node.try_get_context("domain_name")
hosted_zone_id = app.node.try_get_context("hosted_zone_id")
existing_vpc_id = app.node.try_get_context("existing_vpc_id")
existing_alb_arn = app.node.try_get_context("existing_alb_arn")
existing_ecs_cluster_name = app.node.try_get_context("existing_ecs_cluster_name")
existing_db_cluster_id = app.node.try_get_context("existing_db_cluster_id")

TokenburnerBaseStack(
    app,
    "tokenburner-base",
    env=env,
    dev_mode=dev_mode,
    domain_name=domain_name,
    hosted_zone_id=hosted_zone_id,
    existing_vpc_id=existing_vpc_id,
    existing_alb_arn=existing_alb_arn,
    existing_ecs_cluster_name=existing_ecs_cluster_name,
    existing_db_cluster_id=existing_db_cluster_id,
)

app.synth()
