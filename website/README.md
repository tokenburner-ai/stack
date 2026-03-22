# Website

A production-ready static website on CloudFront. Works immediately without a domain — add one whenever you're ready.

## Quick Deploy (no domain needed)

```bash
cd cdk
pip install -r requirements.txt
cdk deploy -c product_name=my-product
```

Your site is live at the CloudFront URL in the output (e.g., `https://d1234abcdef.cloudfront.net`). Done. You can stop here and add a domain later.

## Deploy with a Custom Domain

```bash
cdk deploy -c product_name=my-product -c domain_name=myproduct.com -c subdomain=www
```

This creates `www.myproduct.com` + `myproduct.com` (both point to CloudFront).

## Getting a Domain

If you don't have a domain yet, here's the process:

### Option 1: Buy through Route53 (easiest)

1. Go to [Route53 Domain Registration](https://console.aws.amazon.com/route53/home#/DomainRegistration)
2. Search for your domain name
3. Buy it (~$12/yr for .com, ~$5/yr for .link, varies by TLD)
4. Route53 auto-creates a hosted zone and configures nameservers — no extra steps
5. Deploy with your new domain:
   ```bash
   cdk deploy -c product_name=my-product -c domain_name=myproduct.com
   ```

### Option 2: Buy elsewhere, point to Route53

If you already own a domain (Namecheap, GoDaddy, Google Domains, Cloudflare, etc.):

1. Create a hosted zone in Route53:
   ```bash
   aws route53 create-hosted-zone --name myproduct.com --caller-reference $(date +%s)
   ```

2. Get the nameservers Route53 assigned:
   ```bash
   aws route53 get-hosted-zone --id /hostedzone/Z1234567890 \
     --query 'DelegationSet.NameServers' --output text
   ```
   Output will be 4 nameservers like `ns-123.awsdns-45.com`.

3. Go to your domain registrar and replace the nameservers with the 4 Route53 nameservers.

4. Wait for propagation (usually 15 min – 1 hour, can take up to 48h).

5. Verify it's working:
   ```bash
   dig myproduct.com NS +short
   ```
   Should show Route53 nameservers.

6. Deploy:
   ```bash
   cdk deploy -c product_name=my-product -c domain_name=myproduct.com
   ```

### Option 3: No domain at all

The CloudFront URL (`*.cloudfront.net`) works perfectly. Use this for:
- Development and staging
- Internal tools
- Products that don't need a branded URL yet
- Testing before committing to a domain name

You can add a domain later by redeploying with `-c domain_name=...`. No downtime — CloudFront keeps serving on the old URL too.

## Adding a Domain to an Existing Site

If you deployed without a domain and want to add one later:

```bash
# Just redeploy with the domain context
cdk deploy -c product_name=my-product -c domain_name=myproduct.com -c subdomain=www
```

CDK updates the CloudFront distribution to accept the new domain, creates the TLS certificate, and adds DNS records. The old CloudFront URL continues to work.

## Updating Your Site

Edit files in `static/`, then deploy:

```bash
cdk deploy -c product_name=my-product
```

Or push directly to S3 for faster updates (skips CDK overhead):

```bash
aws s3 sync static/ s3://tokenburner-my-product-site --delete
aws cloudfront create-invalidation --distribution-id YOUR_DIST_ID --paths "/*"
```

## Cost

| Resource | Cost | Notes |
|----------|------|-------|
| CloudFront | ~$0 for low traffic | First 1TB/mo free, then $0.085/GB |
| S3 | < $0.01/mo | Pennies for static files |
| Route53 | $0.50/mo per zone | Only if using custom domain |
| ACM certificate | Free | Auto-renewing |
| **Total** | **$0 – $1/mo** | Essentially free for small sites |

## Structure

```
website/
├── static/
│   ├── index.html      # Landing page template
│   └── style.css       # Dark theme, responsive
├── cdk/
│   ├── app.py          # CDK entry with domain context
│   ├── stack.py        # S3 + CloudFront + optional Route53/ACM
│   ├── cdk.json        # Default context values
│   └── requirements.txt
└── README.md           # This file
```
