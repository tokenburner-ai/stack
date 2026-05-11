"""Tokenburner Base Stack — shared infrastructure for all products.

Two modes:
  dev_mode=True:  DynamoDB + S3 + Secrets Manager + Dashboard Lambda/CF (~$1/mo)
  dev_mode=False: Full stack — VPC, ALB, ECS, Aurora, NAT Gateway (~$71/mo)
"""

import os

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_rds as rds,
    aws_route53 as route53,
    aws_certificatemanager as acm,
    aws_dynamodb as dynamodb,
    aws_secretsmanager as secretsmanager,
    aws_s3 as s3,
    aws_logs as logs,
    aws_lambda as _lambda,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    custom_resources as cr,
)
from constructs import Construct

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")


class TokenburnerBaseStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        dev_mode: bool = False,
        domain_name: str | None = None,
        hosted_zone_id: str | None = None,
        existing_vpc_id: str | None = None,
        existing_alb_arn: str | None = None,
        existing_ecs_cluster_name: str | None = None,
        existing_db_cluster_id: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.dev_mode = dev_mode

        # ──────────────────────────────────────────────
        # Tags — applied to ALL resources in this stack
        # ──────────────────────────────────────────────
        cdk.Tags.of(self).add("ManagedBy", "tokenburner")
        cdk.Tags.of(self).add("tokenburner:stack", "base")
        cdk.Tags.of(self).add("tokenburner:mode", "dev" if dev_mode else "full")

        # ──────────────────────────────────────────────
        # DynamoDB — API Keys table (both modes)
        # ──────────────────────────────────────────────
        self.api_keys_table = dynamodb.Table(
            self,
            "ApiKeys",
            table_name="tokenburner-api-keys",
            partition_key=dynamodb.Attribute(
                name="key_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )
        self.api_keys_table.add_global_secondary_index(
            index_name="name-index",
            partition_key=dynamodb.Attribute(
                name="name",
                type=dynamodb.AttributeType.STRING,
            ),
        )

        # ──────────────────────────────────────────────
        # S3 — Database snapshots bucket (both modes)
        # ──────────────────────────────────────────────
        self.db_snapshots_bucket = s3.Bucket(
            self,
            "DbSnapshots",
            bucket_name=f"tokenburner-db-snapshots-{cdk.Aws.ACCOUNT_ID}-{cdk.Aws.REGION}",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    noncurrent_version_expiration=cdk.Duration.days(30),
                ),
            ],
        )

        # ──────────────────────────────────────────────
        # Google OAuth Secrets (both modes)
        # ──────────────────────────────────────────────
        self.oauth_secret = secretsmanager.Secret(
            self,
            "OAuthSecret",
            secret_name="tokenburner/google-oauth",
            description="Google OAuth client credentials for tokenburner products",
        )

        # ──────────────────────────────────────────────
        # DynamoDB — Feature registry (both modes)
        # ──────────────────────────────────────────────
        self.feature_registry_table = dynamodb.Table(
            self,
            "FeatureRegistry",
            table_name="tokenburner-feature-registry",
            partition_key=dynamodb.Attribute(
                name="name",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # ──────────────────────────────────────────────
        # Bootstrap API key — auto-mint on first deploy
        # Lambda-backed custom resource: generates sk_<32hex>, writes to
        # api-keys table if a bootstrap row does not already exist, returns
        # the key (or existing key) as a stack output.
        # ──────────────────────────────────────────────
        bootstrap_fn = _lambda.Function(
            self,
            "BootstrapKeyFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=cdk.Duration.seconds(30),
            code=_lambda.Code.from_inline(
                "import json, secrets, boto3\n"
                "from datetime import datetime, timezone\n"
                "ddb = boto3.resource('dynamodb')\n"
                "def handler(event, _ctx):\n"
                "    props = event['ResourceProperties']\n"
                "    table = ddb.Table(props['TableName'])\n"
                "    name = props.get('KeyName', 'bootstrap-admin')\n"
                "    if event['RequestType'] == 'Delete':\n"
                "        return {'PhysicalResourceId': event.get('PhysicalResourceId','bootstrap')}\n"
                "    existing = table.scan(\n"
                "        FilterExpression='#n = :n',\n"
                "        ExpressionAttributeNames={'#n': 'name'},\n"
                "        ExpressionAttributeValues={':n': name},\n"
                "    ).get('Items', [])\n"
                "    if existing:\n"
                "        return {'PhysicalResourceId': 'bootstrap', 'Data': {'ApiKey': existing[0]['key_id']}}\n"
                "    key_id = 'sk_' + secrets.token_hex(16)\n"
                "    table.put_item(Item={\n"
                "        'key_id': key_id,\n"
                "        'name': name,\n"
                "        'active': True,\n"
                "        'permissions': ['read', 'write'],\n"
                "        'environments': ['*'],\n"
                "        'created_at': datetime.now(timezone.utc).isoformat(),\n"
                "        'created_by': 'base-stack-bootstrap',\n"
                "        'description': 'Auto-generated admin key for tokenburner dashboard + feature installs',\n"
                "    })\n"
                "    return {'PhysicalResourceId': 'bootstrap', 'Data': {'ApiKey': key_id}}\n"
            ),
        )
        self.api_keys_table.grant_read_write_data(bootstrap_fn)

        bootstrap_provider = cr.Provider(
            self, "BootstrapKeyProvider",
            on_event_handler=bootstrap_fn,
        )

        bootstrap_cr = cdk.CustomResource(
            self, "BootstrapKey",
            service_token=bootstrap_provider.service_token,
            properties={
                "TableName": self.api_keys_table.table_name,
                "KeyName": "bootstrap-admin",
            },
        )

        bootstrap_key = bootstrap_cr.get_att_string("ApiKey")

        # ──────────────────────────────────────────────
        # Dashboard Lambda + CloudFront (both modes)
        # ──────────────────────────────────────────────
        dashboard_fn = _lambda.Function(
            self,
            "DashboardFn",
            function_name="tokenburner-dashboard",
            runtime=_lambda.Runtime.PYTHON_3_12,
            architecture=_lambda.Architecture.ARM_64,
            handler="lambda_handler.handler",
            memory_size=512,
            timeout=cdk.Duration.seconds(30),
            code=_lambda.Code.from_asset(
                path=DASHBOARD_DIR,
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    platform="linux/arm64",
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output --quiet && "
                        "cp -r app /asset-output/ && "
                        "cp lambda_handler.py /asset-output/ && "
                        "cp -r static /asset-output/",
                    ],
                ),
            ),
            environment={
                "API_KEYS_TABLE": self.api_keys_table.table_name,
                "FEATURE_REGISTRY_TABLE": self.feature_registry_table.table_name,
            },
        )

        # IAM: read api-keys (for auth) and update last_used_at
        dashboard_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
                resources=[self.api_keys_table.table_arn],
            )
        )
        # IAM: scan feature-registry (for /api/features)
        dashboard_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:Scan"],
                resources=[self.feature_registry_table.table_arn],
            )
        )

        dashboard_url = dashboard_fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.NONE,
        )

        self.dashboard_distribution = cloudfront.Distribution(
            self,
            "DashboardCdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.FunctionUrlOrigin(dashboard_url),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
            ),
        )

        # ──────────────────────────────────────────────
        # Exports (both modes)
        # ──────────────────────────────────────────────
        self._export("api-keys-table-name", self.api_keys_table.table_name)
        self._export("api-keys-table-arn", self.api_keys_table.table_arn)
        self._export("feature-registry-table-name", self.feature_registry_table.table_name)
        self._export("feature-registry-table-arn", self.feature_registry_table.table_arn)
        self._export("oauth-secret-arn", self.oauth_secret.secret_arn)
        self._export("db-snapshots-bucket", self.db_snapshots_bucket.bucket_name)
        self._export("dashboard-url", f"https://{self.dashboard_distribution.distribution_domain_name}")
        self._export("mode", "dev" if dev_mode else "full")

        # Surface the bootstrap key + dashboard URL as named outputs so the
        # CLI can parse them after `cdk deploy`.
        cdk.CfnOutput(
            self, "DashboardUrl",
            value=f"https://{self.dashboard_distribution.distribution_domain_name}",
            description="Tokenburner dashboard URL — open this in your browser",
        )
        cdk.CfnOutput(
            self, "BootstrapApiKey",
            value=bootstrap_key,
            description="Admin API key for the dashboard and feature installs. Save this now.",
        )

        # ──────────────────────────────────────────────
        # Dev mode stops here — no VPC, ALB, ECS, Aurora
        # ──────────────────────────────────────────────
        if dev_mode:
            return

        # ══════════════════════════════════════════════
        # FULL STACK — everything below is production
        # ══════════════════════════════════════════════

        # ──────────────────────────────────────────────
        # VPC
        # ──────────────────────────────────────────────
        if existing_vpc_id:
            self.vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=existing_vpc_id)
        else:
            self.vpc = ec2.Vpc(
                self,
                "Vpc",
                vpc_name="tokenburner",
                max_azs=2,
                nat_gateways=1,
                subnet_configuration=[
                    ec2.SubnetConfiguration(
                        name="Public",
                        subnet_type=ec2.SubnetType.PUBLIC,
                        cidr_mask=24,
                    ),
                    ec2.SubnetConfiguration(
                        name="Private",
                        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                        cidr_mask=24,
                    ),
                ],
            )

        # ──────────────────────────────────────────────
        # Route53 Hosted Zone + ACM Certificate
        # ──────────────────────────────────────────────
        self.hosted_zone = None
        self.certificate = None

        if domain_name:
            if hosted_zone_id:
                self.hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
                    self,
                    "Zone",
                    zone_name=domain_name,
                    hosted_zone_id=hosted_zone_id,
                )
            else:
                self.hosted_zone = route53.HostedZone(
                    self,
                    "Zone",
                    zone_name=domain_name,
                )

            self.certificate = acm.Certificate(
                self,
                "WildcardCert",
                domain_name=domain_name,
                subject_alternative_names=[f"*.{domain_name}"],
                validation=acm.CertificateValidation.from_dns(self.hosted_zone),
            )

        # ──────────────────────────────────────────────
        # Application Load Balancer
        # ──────────────────────────────────────────────
        if existing_alb_arn:
            self.alb = elbv2.ApplicationLoadBalancer.from_application_load_balancer_attributes(
                self,
                "Alb",
                load_balancer_arn=existing_alb_arn,
                security_group_id="",
                vpc=self.vpc,
            )
            self.https_listener = None
        else:
            self.alb = elbv2.ApplicationLoadBalancer(
                self,
                "Alb",
                load_balancer_name="tokenburner",
                vpc=self.vpc,
                internet_facing=True,
            )

            if self.certificate:
                self.alb.add_redirect(source_port=80, target_port=443)
                self.https_listener = self.alb.add_listener(
                    "HttpsListener",
                    port=443,
                    certificates=[self.certificate],
                    default_action=elbv2.ListenerAction.fixed_response(
                        status_code=404,
                        content_type="text/plain",
                        message_body="Not found",
                    ),
                )
            else:
                self.https_listener = self.alb.add_listener(
                    "HttpListener",
                    port=80,
                    default_action=elbv2.ListenerAction.fixed_response(
                        status_code=200,
                        content_type="text/html",
                        message_body=(
                            "<!DOCTYPE html><html><head><meta charset=utf-8>"
                            "<title>tokenburner</title>"
                            "<style>*{margin:0;padding:0;box-sizing:border-box}"
                            "body{background:#050508;color:#f0f0f0;font-family:system-ui,sans-serif;"
                            "display:flex;align-items:center;justify-content:center;min-height:100vh;"
                            "text-align:center}"
                            "h1{font-size:2.5rem;font-weight:800;"
                            "background:linear-gradient(135deg,#fff,#f97316,#3b82f6);"
                            "-webkit-background-clip:text;-webkit-text-fill-color:transparent}"
                            "p{color:#777;margin-top:1rem;font-size:1.1rem}"
                            "a{color:#f97316;text-decoration:none}"
                            ".f{font-size:2rem;margin-bottom:1rem}"
                            "</style></head><body><div>"
                            "<div class=f>&#x1F525;</div>"
                            "<h1>Burned a few to build this</h1>"
                            "<p>tokenburner base stack is live.</p>"
                            "<p style='margin-top:2rem;font-size:.85rem'>"
                            "Brought to you by <a href='https://github.com/tokenburner-ai'>tokenburner</a>"
                            "</p></div></body></html>"
                        ),
                    ),
                )

        # ──────────────────────────────────────────────
        # ECS Cluster
        # ──────────────────────────────────────────────
        if existing_ecs_cluster_name:
            self.ecs_cluster = ecs.Cluster.from_cluster_attributes(
                self,
                "Cluster",
                cluster_name=existing_ecs_cluster_name,
                vpc=self.vpc,
                security_groups=[],
            )
        else:
            self.ecs_cluster = ecs.Cluster(
                self,
                "Cluster",
                cluster_name="tokenburner",
                vpc=self.vpc,
                container_insights_v2=ecs.ContainerInsights.DISABLED,
            )

        # ──────────────────────────────────────────────
        # Aurora PostgreSQL Serverless v2
        # ──────────────────────────────────────────────
        self.db_secret = None
        self.db_cluster = None

        if not existing_db_cluster_id:
            self.db_secret = secretsmanager.Secret(
                self,
                "DbSecret",
                secret_name="tokenburner/db",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    secret_string_template='{"username":"tokenburner"}',
                    generate_string_key="password",
                    exclude_punctuation=True,
                    password_length=32,
                ),
            )

            self.db_security_group = ec2.SecurityGroup(
                self,
                "DbSg",
                vpc=self.vpc,
                description="Aurora PostgreSQL access",
                allow_all_outbound=False,
            )
            self.db_security_group.add_ingress_rule(
                ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
                ec2.Port.tcp(5432),
                "PostgreSQL from VPC",
            )

            self.db_cluster = rds.DatabaseCluster(
                self,
                "Database",
                engine=rds.DatabaseClusterEngine.aurora_postgres(
                    version=rds.AuroraPostgresEngineVersion.VER_16_4,
                ),
                cluster_identifier="tokenburner",
                default_database_name="tokenburner",
                credentials=rds.Credentials.from_secret(self.db_secret),
                vpc=self.vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                ),
                security_groups=[self.db_security_group],
                serverless_v2_min_capacity=0.5,
                serverless_v2_max_capacity=4,
                writer=rds.ClusterInstance.serverless_v2("writer"),
                storage_encrypted=True,
                removal_policy=cdk.RemovalPolicy.SNAPSHOT,
            )

        # ──────────────────────────────────────────────
        # Full-stack CloudFormation Exports
        # ──────────────────────────────────────────────
        self._export("vpc-id", self.vpc.vpc_id)
        self._export(
            "public-subnets",
            ",".join([s.subnet_id for s in self.vpc.public_subnets]),
        )
        self._export(
            "private-subnets",
            ",".join([s.subnet_id for s in self.vpc.private_subnets]),
        )

        if not existing_alb_arn:
            self._export("alb-arn", self.alb.load_balancer_arn)
            self._export("alb-dns", self.alb.load_balancer_dns_name)
            self._export(
                "alb-security-group",
                self.alb.connections.security_groups[0].security_group_id,
            )
            if self.https_listener:
                self._export("alb-listener-arn", self.https_listener.listener_arn)

        self._export("ecs-cluster-name", self.ecs_cluster.cluster_name)
        self._export("ecs-cluster-arn", self.ecs_cluster.cluster_arn)

        if self.hosted_zone:
            self._export("route53-zone-id", self.hosted_zone.hosted_zone_id)
            self._export("route53-zone-name", self.hosted_zone.zone_name)

        if self.certificate:
            self._export("certificate-arn", self.certificate.certificate_arn)

        if self.db_cluster:
            self._export("db-cluster-endpoint", self.db_cluster.cluster_endpoint.hostname)
            self._export("db-cluster-port", str(self.db_cluster.cluster_endpoint.port))
        if self.db_secret:
            self._export("db-secret-arn", self.db_secret.secret_arn)

    def _export(self, name: str, value: str) -> None:
        """Create a CfnOutput with a standardized export name."""
        cdk.CfnOutput(
            self,
            name,
            value=value,
            export_name=f"tokenburner-{name}",
        )
