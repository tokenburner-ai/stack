"""Static SPA Pattern — S3 + CloudFront + Route53.

Deploy a static frontend (HTML/JS/CSS) to a global CDN.
Use this for dashboards, marketing sites, or standalone frontends
that talk to a separate API backend.

Usage:
    Copy this into your product's cdk/ directory and merge with
    your existing stack, or use as a standalone stack.
"""

import aws_cdk as cdk
from aws_cdk import (
    aws_s3 as s3,
    aws_s3_deployment as s3_deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as targets,
)
from constructs import Construct


class StaticSpaStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        product_name: str,
        subdomain: str,
        static_dir: str = "../static",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ──────────────────────────────────────────────
        # S3 Bucket for static assets
        # ──────────────────────────────────────────────
        bucket = s3.Bucket(
            self,
            "StaticBucket",
            bucket_name=f"tokenburner-{product_name}-static",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ──────────────────────────────────────────────
        # CloudFront Distribution
        # ──────────────────────────────────────────────

        # Import domain info from base stack (optional)
        zone_id = None
        zone_name = None
        certificate = None
        domain_names = None

        try:
            zone_id = cdk.Fn.import_value("tokenburner-route53-zone-id")
            zone_name = cdk.Fn.import_value("tokenburner-route53-zone-name")
            cert_arn = cdk.Fn.import_value("tokenburner-certificate-arn")

            # CloudFront needs a us-east-1 cert — if the base cert is in the
            # same region, you may need a separate cert. For simplicity, we
            # attempt to use the base cert (works if base is us-east-1).
            certificate = acm.Certificate.from_certificate_arn(
                self, "Cert", cert_arn
            )
            domain_names = [f"{subdomain}.{zone_name}"]
        except Exception:
            pass

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            # SPA routing — serve index.html for all 404s
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_page_path="/index.html",
                    response_http_status=200,
                    ttl=cdk.Duration.seconds(0),
                ),
            ],
            certificate=certificate,
            domain_names=domain_names,
        )

        # ──────────────────────────────────────────────
        # Deploy static files to S3
        # ──────────────────────────────────────────────
        s3_deploy.BucketDeployment(
            self,
            "DeployStatic",
            sources=[s3_deploy.Source.asset(static_dir)],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ──────────────────────────────────────────────
        # Route53 Record (if domain configured)
        # ──────────────────────────────────────────────
        if zone_id and zone_name:
            zone = route53.HostedZone.from_hosted_zone_attributes(
                self, "Zone", zone_name=zone_name, hosted_zone_id=zone_id
            )
            route53.ARecord(
                self,
                "DnsRecord",
                zone=zone,
                record_name=subdomain,
                target=route53.RecordTarget.from_alias(
                    targets.CloudFrontTarget(distribution)
                ),
            )

        # ──────────────────────────────────────────────
        # Outputs
        # ──────────────────────────────────────────────
        cdk.CfnOutput(self, "DistributionUrl",
                       value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "BucketName", value=bucket.bucket_name)
