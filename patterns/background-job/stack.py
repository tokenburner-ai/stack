"""Background Job Pattern — Lambda + RDS Proxy.

Use for event-driven processing, webhooks, scheduled tasks.
Connects to Aurora via RDS Proxy to avoid connection exhaustion.

Usage:
    Merge into your product's CDK stack, or use standalone.
"""

import os
import aws_cdk as cdk
from aws_cdk import (
    aws_lambda as _lambda,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_apigateway as apigw,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class BackgroundJobStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        product_name: str,
        handler_dir: str = "../jobs",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ──────────────────────────────────────────────
        # Tags
        # ──────────────────────────────────────────────
        cdk.Tags.of(self).add("ManagedBy", "tokenburner")
        cdk.Tags.of(self).add("tokenburner:stack", "product")
        cdk.Tags.of(self).add("tokenburner:product", product_name)
        cdk.Tags.of(self).add("tokenburner:pattern", "background-job")

        # ──────────────────────────────────────────────
        # Import base stack resources
        # ──────────────────────────────────────────────
        vpc_id = cdk.Fn.import_value("tokenburner-vpc-id")
        vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=vpc_id)

        db_secret_arn = cdk.Fn.import_value("tokenburner-db-secret-arn")
        db_secret = secretsmanager.Secret.from_secret_complete_arn(
            self, "DbSecret", secret_complete_arn=db_secret_arn
        )

        # ──────────────────────────────────────────────
        # Lambda Function
        # ──────────────────────────────────────────────
        fn = _lambda.Function(
            self,
            "JobHandler",
            function_name=f"tokenburner-{product_name}-job",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.main",
            code=_lambda.Code.from_asset(handler_dir),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            memory_size=256,
            timeout=cdk.Duration.seconds(60),
            environment={
                "PRODUCT_NAME": product_name,
                "DB_SECRET_ARN": db_secret_arn,
            },
            log_retention=logs.RetentionDays.TWO_WEEKS,
        )

        # Grant DB secret access
        db_secret.grant_read(fn)

        # Grant Bedrock access (if job uses AI)
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )

        # ──────────────────────────────────────────────
        # Trigger: Scheduled (cron)
        # Uncomment and modify as needed.
        # ──────────────────────────────────────────────
        # events.Rule(
        #     self,
        #     "ScheduleRule",
        #     schedule=events.Schedule.rate(cdk.Duration.hours(1)),
        #     targets=[events_targets.LambdaFunction(fn)],
        # )

        # ──────────────────────────────────────────────
        # Trigger: API Gateway (webhook)
        # Uncomment and modify as needed.
        # ──────────────────────────────────────────────
        # api = apigw.RestApi(
        #     self,
        #     "WebhookApi",
        #     rest_api_name=f"tokenburner-{product_name}-webhook",
        # )
        # webhook = api.root.add_resource("webhook")
        # webhook.add_method("POST", apigw.LambdaIntegration(fn))

        # ──────────────────────────────────────────────
        # Outputs
        # ──────────────────────────────────────────────
        cdk.CfnOutput(self, "FunctionName", value=fn.function_name)
        cdk.CfnOutput(self, "FunctionArn", value=fn.function_arn)
