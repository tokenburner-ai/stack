"""Product Stack — Fargate service behind the shared tokenburner ALB."""

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
)
from constructs import Construct


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

        # ──────────────────────────────────────────────
        # Import base stack resources
        # ──────────────────────────────────────────────
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

        # Route53 zone (optional — may not exist if no domain)
        zone_id = None
        zone_name = None
        try:
            zone_id = cdk.Fn.import_value("tokenburner-route53-zone-id")
            zone_name = cdk.Fn.import_value("tokenburner-route53-zone-name")
        except Exception:
            pass

        # ──────────────────────────────────────────────
        # Log Group
        # ──────────────────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "Logs",
            log_group_name=f"/tokenburner/{product_name}",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ──────────────────────────────────────────────
        # Fargate Task Definition
        # ──────────────────────────────────────────────
        task_def = ecs.FargateTaskDefinition(
            self,
            "TaskDef",
            cpu=256,
            memory_limit_mib=512,
        )

        # Grant secret access
        db_secret.grant_read(task_def.task_role)
        oauth_secret.grant_read(task_def.task_role)

        # Grant API keys table read + update (for last_used_at tracking)
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:UpdateItem",
                ],
                resources=[
                    cdk.Fn.import_value("tokenburner-api-keys-table-arn"),
                    f"{cdk.Fn.import_value('tokenburner-api-keys-table-arn')}/index/*",
                ],
            )
        )

        # Grant Bedrock invoke access (for AI features)
        task_def.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )

        container = task_def.add_container(
            "App",
            image=ecs.ContainerImage.from_asset(os.path.join(os.path.dirname(__file__), "..")),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix=product_name,
                log_group=log_group,
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

        # ──────────────────────────────────────────────
        # Fargate Service
        # ──────────────────────────────────────────────
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

        # ──────────────────────────────────────────────
        # ALB Target Group + Listener Rule
        # ──────────────────────────────────────────────
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

        # Route by host header: subdomain.domain.com
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

        # ──────────────────────────────────────────────
        # Route53 Record (if domain configured)
        # ──────────────────────────────────────────────
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
        """Generate a deterministic ALB listener rule priority from the product name."""
        # Hash to a number between 1-50000 to avoid collisions
        return (hash(name) % 49999) + 1
