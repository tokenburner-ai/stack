"""Website Stack — S3 + CloudFront with optional custom domain.

Deploys immediately on a CloudFront URL (*.cloudfront.net).
Custom domain can be added at deploy time or later.

Usage:
    # No domain — live instantly on CloudFront URL
    cdk deploy

    # With domain
    cdk deploy -c domain_name=myproduct.com -c subdomain=www
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


class WebsiteStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        product_name: str,
        domain_name: str | None = None,
        subdomain: str = "www",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ──────────────────────────────────────────────
        # Tags
        # ──────────────────────────────────────────────
        cdk.Tags.of(self).add("ManagedBy", "tokenburner")
        cdk.Tags.of(self).add("tokenburner:stack", "website")
        cdk.Tags.of(self).add("tokenburner:product", product_name)

        # ──────────────────────────────────────────────
        # S3 Bucket
        # ──────────────────────────────────────────────
        bucket = s3.Bucket(
            self,
            "SiteBucket",
            bucket_name=f"tokenburner-{product_name}-site",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        # ──────────────────────────────────────────────
        # Domain + Certificate (optional)
        # ──────────────────────────────────────────────
        certificate = None
        site_domain_names = None
        hosted_zone = None

        if domain_name:
            # Build the full site hostname
            if subdomain and subdomain != "@":
                site_hostname = f"{subdomain}.{domain_name}"
            else:
                site_hostname = domain_name

            # Look up or create hosted zone
            # First try importing from base stack
            try:
                zone_id = cdk.Fn.import_value("tokenburner-route53-zone-id")
                zone_name_export = cdk.Fn.import_value("tokenburner-route53-zone-name")
                hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
                    self, "Zone", zone_name=zone_name_export, hosted_zone_id=zone_id
                )
            except Exception:
                # No base stack zone — look up by domain name
                hosted_zone = route53.HostedZone.from_lookup(
                    self, "Zone", domain_name=domain_name
                )

            # CloudFront requires certs in us-east-1
            certificate = acm.DnsValidatedCertificate(
                self,
                "SiteCert",
                domain_name=site_hostname,
                hosted_zone=hosted_zone,
                region="us-east-1",
            )

            site_domain_names = [site_hostname]

            # Also cover apex if we're deploying www
            if subdomain == "www":
                site_domain_names.append(domain_name)
                certificate_apex = acm.DnsValidatedCertificate(
                    self,
                    "ApexCert",
                    domain_name=domain_name,
                    hosted_zone=hosted_zone,
                    region="us-east-1",
                )

        # ──────────────────────────────────────────────
        # CloudFront Distribution
        # ──────────────────────────────────────────────
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_page_path="/index.html",
                    response_http_status=200,
                    ttl=cdk.Duration.seconds(0),
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_page_path="/index.html",
                    response_http_status=200,
                    ttl=cdk.Duration.seconds(0),
                ),
            ],
            certificate=certificate,
            domain_names=site_domain_names,
        )

        # ──────────────────────────────────────────────
        # Deploy static files
        # ──────────────────────────────────────────────
        s3_deploy.BucketDeployment(
            self,
            "DeploySite",
            sources=[s3_deploy.Source.asset("../static")],
            destination_bucket=bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # ──────────────────────────────────────────────
        # DNS Records (if domain configured)
        # ──────────────────────────────────────────────
        if hosted_zone and domain_name:
            if subdomain and subdomain != "@":
                route53.ARecord(
                    self,
                    "SubdomainRecord",
                    zone=hosted_zone,
                    record_name=subdomain,
                    target=route53.RecordTarget.from_alias(
                        targets.CloudFrontTarget(distribution)
                    ),
                )

            # Apex record (always — either as primary or redirect target)
            route53.ARecord(
                self,
                "ApexRecord",
                zone=hosted_zone,
                target=route53.RecordTarget.from_alias(
                    targets.CloudFrontTarget(distribution)
                ),
            )

        # ──────────────────────────────────────────────
        # Outputs
        # ──────────────────────────────────────────────
        cdk.CfnOutput(
            self,
            "CloudFrontUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description="Site URL (always works, even without a custom domain)",
        )
        cdk.CfnOutput(self, "BucketName", value=bucket.bucket_name)
        cdk.CfnOutput(
            self,
            "DistributionId",
            value=distribution.distribution_id,
            description="Use for cache invalidation: aws cloudfront create-invalidation --distribution-id <id> --paths '/*'",
        )
        if site_domain_names:
            cdk.CfnOutput(
                self,
                "SiteUrl",
                value=f"https://{site_domain_names[0]}",
                description="Custom domain URL",
            )
