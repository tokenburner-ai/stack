# Setup Domain — Tokenburner Context

This context is loaded by `tokenburner domain`. It guides you through attaching a custom domain.

> **Status: Not yet implemented.** This is a planned feature. The domain setup will involve:
>
> 1. Route53 hosted zone creation (or import existing)
> 2. ACM wildcard certificate request + DNS validation
> 3. CloudFront alternate domain name configuration
> 4. ALB HTTPS listener (for full stack mode)
> 5. Subdomain routing for multiple products (e.g., storage.tokenburner.ai, api.tokenburner.ai)
>
> For now, products are accessible via their CloudFront distribution URLs.
