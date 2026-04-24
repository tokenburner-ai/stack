"""Product Stack — two deployment modes.

DevProductStack:  Lambda + CloudFront (~$0/mo, dev mode)
ProductStack:     Fargate + ALB (production, full stack)
"""

import os
import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_logs as logs,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    aws_lambda as _lambda,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
)
from constructs import Construct

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


# ══════════════════════════════════════════════════════
# Dev Mode: Lambda + CloudFront
# ══════════════════════════════════════════════════════

class DevProductStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        product_name: str,
        name_suffix: str = "",
        api_keys_table_name: str | None = None,
        api_keys_table_arn: str | None = None,
        db_snapshots_bucket: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cdk.Tags.of(self).add("ManagedBy", "tokenburner")
        cdk.Tags.of(self).add("tokenburner:stack", "product")
        cdk.Tags.of(self).add("tokenburner:product", product_name)
        cdk.Tags.of(self).add("tokenburner:mode", "dev")

        # Use provided values or import from base stack exports
        api_keys_table_name = api_keys_table_name or cdk.Fn.import_value("tokenburner-api-keys-table-name")
        api_keys_table_arn  = api_keys_table_arn  or cdk.Fn.import_value("tokenburner-api-keys-table-arn")
        db_snapshots_bucket = db_snapshots_bucket or cdk.Fn.import_value("tokenburner-db-snapshots-bucket")

        # ──────────────────────────────────────────────
        # Lambda Function (Flask app via mangum)
        # ──────────────────────────────────────────────
        fn = _lambda.Function(
            self,
            "Handler",
            function_name=f"tokenburner-{product_name}{name_suffix}",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.ARM_64,
            handler="lambda_handler.handler",
            code=_lambda.Code.from_asset(
                path=PROJECT_ROOT,
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    platform="linux/arm64",
                    command=[
                        "bash", "-c",
                        "pip install flask apig-wsgi boto3 flasgger -t /asset-output --quiet && "
                        "cp -r app/* /asset-output/ && "
                        "cp lambda_handler.py /asset-output/ && "
                        "cp -r migrations /asset-output/ && "
                        "cp -r static /asset-output/"
                    ],
                ),
            ),
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            environment={
                "PRODUCT_NAME": product_name,
                "S3_DB_BUCKET": db_snapshots_bucket,
                "S3_DB_KEY": f"{product_name}{name_suffix}/dev.sqlite",
                "API_KEYS_TABLE": api_keys_table_name,
            },
        )

        # IAM: DynamoDB API keys (read + update last_used_at)
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
                resources=[api_keys_table_arn, f"{api_keys_table_arn}/index/*"],
            )
        )

        # IAM: S3 for SQLite database
        bucket_arn = f"arn:aws:s3:::{db_snapshots_bucket}"
        fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject", "s3:HeadObject"],
                resources=[f"{bucket_arn}/{product_name}/*"],
            )
        )

        # Lambda function URL (public — CloudFront is the entry point)
        fn_url = fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )

        # ──────────────────────────────────────────────
        # CloudFront Distribution
        # ──────────────────────────────────────────────
        self.distribution = cloudfront.Distribution(
            self,
            "CDN",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.FunctionUrlOrigin(fn_url),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            ),
        )

        # ──────────────────────────────────────────────
        # Outputs
        # ──────────────────────────────────────────────
        cdk.CfnOutput(self, "AppUrl",
                       value=f"https://{self.distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "LambdaFunctionUrl", value=fn_url.url,
                       description="Lambda function URL — use as /api/* origin for website CloudFront")
        cdk.CfnOutput(self, "CloudFrontDomain",
                       value=self.distribution.distribution_domain_name)


# ══════════════════════════════════════════════════════
# Full Stack: Fargate + ALB
# ══════════════════════════════════════════════════════

class ProductStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        product_name: str,
        subdomain: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cdk.Tags.of(self).add("ManagedBy", "tokenburner")
        cdk.Tags.of(self).add("tokenburner:stack", "product")
        cdk.Tags.of(self).add("tokenburner:product", product_name)

        # Import base stack resources
        vpc_id = cdk.Fn.import_value("tokenburner-vpc-id")
        vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=vpc_id)

        cluster_name = cdk.Fn.import_value("tokenburner-ecs-cluster-name")
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "Cluster", cluster_name=cluster_name, vpc=vpc, security_groups=[]
        )

        listener_arn = cdk.Fn.import_value("tokenburner-alb-listener-arn")
        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self,
            "Listener",
            listener_arn=listener_arn,
            security_group=ec2.SecurityGroup.from_security_group_id(
                self,
                "AlbSg",
                cdk.Fn.import_value("tokenburner-alb-security-group"),
            ),
        )

        db_secret_arn = cdk.Fn.import_value("tokenburner-db-secret-arn")
        db_secret = secretsmanager.Secret.from_secret_complete_arn(
            self, "DbSecret", secret_complete_arn=db_secret_arn
        )

        db_endpoint = cdk.Fn.import_value("tokenburner-db-cluster-endpoint")
        db_port = cdk.Fn.import_value("tokenburner-db-cluster-port")

        api_keys_table_name = cdk.Fn.import_value("tokenburner-api-keys-table-name")

        oauth_secret_arn = cdk.Fn.import_value("tokenburner-oauth-secret-arn")
        oauth_secret = secretsmanager.Secret.from_secret_complete_arn(
            self, "OAuthSecret", secret_complete_arn=oauth_secret_arn
        )

        zone_id = None
        zone_name = None
        try:
            zone_id = cdk.Fn.import_value("tokenburner-route53-zone-id")
            zone_name = cdk.Fn.import_value("tokenburner-route53-zone-name")
        except Exception:
            pass

        # Log Group
        log_group = logs.LogGroup(
            self,
            "Logs",
            log_group_name=f"/tokenburner/{product_name}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # Fargate Task Definition
        task_def = ecs.FargateTaskDefinition(
            self, "TaskDef", cpu=256, memory_limit_mib=512,
        )

        db_secret.grant_read(task_def.task_role)
        oauth_secret.grant_read(task_def.task_role)

        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
                resources=[
                    cdk.Fn.import_value("tokenburner-api-keys-table-arn"),
                    f"{cdk.Fn.import_value('tokenburner-api-keys-table-arn')}/index/*",
                ],
            )
        )

        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )

        container = task_def.add_container(
            "App",
            image=ecs.ContainerImage.from_asset(PROJECT_ROOT),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix=product_name, log_group=log_group,
            ),
            environment={
                "PRODUCT_NAME": product_name,
                "DB_HOST": db_endpoint,
                "DB_PORT": db_port,
                "DB_NAME": "tokenburner",
                "API_KEYS_TABLE": api_keys_table_name,
                "AWS_REGION": self.region,
            },
            secrets={
                "DB_SECRET_JSON": ecs.Secret.from_secrets_manager(db_secret),
                "GOOGLE_CLIENT_ID": ecs.Secret.from_secrets_manager(oauth_secret, field="client_id"),
                "GOOGLE_CLIENT_SECRET": ecs.Secret.from_secrets_manager(oauth_secret, field="client_secret"),
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
                interval=cdk.Duration.seconds(30),
                timeout=cdk.Duration.seconds(5),
                retries=3,
            ),
        )
        container.add_port_mappings(
            ecs.PortMapping(container_port=8080, protocol=ecs.Protocol.TCP)
        )

        # Fargate Service
        service = ecs.FargateService(
            self,
            "Service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            assign_public_ip=False,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
        )

        # ALB Target Group + Listener Rule
        target_group = elbv2.ApplicationTargetGroup(
            self,
            "TargetGroup",
            vpc=vpc,
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                interval=cdk.Duration.seconds(30),
            ),
        )

        elbv2.ApplicationListenerRule(
            self,
            "ListenerRule",
            listener=listener,
            priority=self._priority_from_name(product_name),
            conditions=[
                elbv2.ListenerCondition.host_headers([f"{subdomain}.*"]),
            ],
            target_groups=[target_group],
        )

        # Route53 Record (if domain configured)
        if zone_id and zone_name:
            alb_dns = cdk.Fn.import_value("tokenburner-alb-dns")
            zone = route53.HostedZone.from_hosted_zone_attributes(
                self, "Zone", zone_name=zone_name, hosted_zone_id=zone_id
            )
            route53.ARecord(
                self,
                "DnsRecord",
                zone=zone,
                record_name=subdomain,
                target=route53.RecordTarget.from_alias(
                    targets.LoadBalancerTarget(
                        elbv2.ApplicationLoadBalancer.from_application_load_balancer_attributes(
                            self,
                            "AlbForDns",
                            load_balancer_arn=cdk.Fn.import_value("tokenburner-alb-arn"),
                            security_group_id=cdk.Fn.import_value("tokenburner-alb-security-group"),
                            vpc=vpc,
                        )
                    )
                ),
            )

    @staticmethod
    def _priority_from_name(name: str) -> int:
        return (hash(name) % 49999) + 1
