---
name: cloudfront-s3-oac
description: Securely serve private S3 content through CloudFront using Origin Access Control (OAC). Use when you need to make S3 files publicly accessible over a CDN without making the bucket itself public — e.g. hosting static sites, media, downloads, or podcast/web artifacts. Covers the modern OAC approach (AWS-recommended), migrating legacy OAI distributions to OAC, locking down the bucket Public Access Block, enforcing HTTPS, and verifying the result. Never make an S3 bucket public directly.
---

# CloudFront + S3 with Origin Access Control (OAC)

## Overview

The goal: let the public download S3 objects through a CloudFront CDN, while the
S3 bucket stays fully private. CloudFront authenticates to S3 with a signed
identity; the bucket policy only trusts that one CloudFront distribution. The
public never touches S3 directly.

**Use OAC, not OAI.** Origin Access Control (OAC) is the current AWS-recommended
mechanism. Origin Access Identity (OAI) is legacy — it does not support
SSE-KMS-encrypted buckets, fails in newer regions, and AWS has stopped investing
in it. New setups use OAC; existing OAI distributions should be migrated.

```
Public user → custom domain (e.g. media.example.com)
            → CloudFront distribution (dxxxx.cloudfront.net)
            → CloudFront signs request with OAC (SigV4)
            → reads PRIVATE S3 bucket
            → returns object to user
```

## Security Rules (MUST follow)

- **MUST NEVER make the S3 bucket public.** No `Principal: "*"` in the bucket
  policy. No public ACLs. The only reader is the CloudFront distribution.
- **MUST turn ALL four Public Access Block switches ON** (`true`). OAC reads the
  bucket via the bucket policy, which Public Access Block does NOT interfere with.
  Leaving them `false` means a single fat-fingered policy edit silently exposes
  everything. Consequence: a private media bucket becomes a public data leak.
- **MUST scope the bucket policy to the exact distribution ARN** via the
  `AWS:SourceArn` condition, so only THAT distribution can read — not any
  CloudFront distribution in any account.
- **MUST enforce HTTPS** — set the viewer protocol policy to `redirect-to-https`,
  never `allow-all` (which serves plaintext HTTP).
- **Before any change to an existing distribution/bucket, back up the current
  config to JSON and state the rollback path.** These are live public endpoints.

## Quick Start — brand-new OAC setup

Assumes a private bucket `MY_BUCKET` in region `MY_REGION` already holds the files.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET=MY_BUCKET
REGION=MY_REGION

# 1. Lock the bucket down — all Public Access Block switches ON
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# 2. Create an OAC (sign every request with SigV4)
OAC_ID=$(aws cloudfront create-origin-access-control \
  --origin-access-control-config \
  "Name=${BUCKET}-oac,Description=OAC for ${BUCKET},SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3" \
  --query 'OriginAccessControl.Id' --output text)
echo "OAC_ID=$OAC_ID"

# 3. Create the distribution with the S3 REST endpoint as origin + the OAC.
#    Use the regional REST endpoint: <bucket>.s3.<region>.amazonaws.com
#    (NOT the website endpoint). See references/distribution-config.json for a
#    full ready-to-edit config you can pass to create-distribution.

# 4. Attach the bucket policy that trusts ONLY this distribution (see below).
```

Then attach the bucket policy (replace the three placeholders):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowCloudFrontServicePrincipalReadOnly",
    "Effect": "Allow",
    "Principal": { "Service": "cloudfront.amazonaws.com" },
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::MY_BUCKET/*",
    "Condition": {
      "StringEquals": {
        "AWS:SourceArn": "arn:aws:cloudfront::ACCOUNT_ID:distribution/DISTRIBUTION_ID"
      }
    }
  }]
}
```

```bash
aws s3api put-bucket-policy --bucket "$BUCKET" --policy file://bucket-policy.json
```

## Migrating a legacy OAI distribution to OAC

Symptom you'll find on old setups: the distribution origin has
`S3OriginConfig.OriginAccessIdentity = origin-access-identity/cloudfront/XXXX`
and the bucket policy trusts a principal like
`arn:aws:iam::cloudfront:user/CloudFront Origin Access Identity XXXX`.

Migration steps (no file movement, fully reversible):

1. **Back up first:**
   ```bash
   aws cloudfront get-distribution-config --id DIST_ID > /tmp/dist-backup.json
   aws s3api get-bucket-policy --bucket BUCKET --query Policy --output text > /tmp/policy-backup.json
   ```
2. Create an OAC (step 2 above).
3. `get-distribution-config` → edit the JSON: set `OriginAccessControlId` to the
   new OAC, blank out `S3OriginConfig.OriginAccessIdentity` (set to `""`), keep
   the `ETag` for the `--if-match` flag.
4. `update-distribution --id DIST_ID --if-match ETAG --distribution-config file://edited.json`
5. Replace the bucket policy with the OAC-style policy (Service principal +
   `AWS:SourceArn` condition) shown above.
6. Flip the Public Access Block to all-`true` if it wasn't already.
7. Wait for the distribution to redeploy (`Status: Deployed`), then verify.

Keep the old OAI around until verification passes; delete it only after.

## Verification (always do this before declaring done)

```bash
# 1. CDN serves the file over HTTPS
curl -sI https://YOUR_DOMAIN_OR_CF_DOMAIN/path/to/object | head -5
#    expect: HTTP/2 200

# 2. Direct S3 access is DENIED (the whole point)
curl -sI https://BUCKET.s3.REGION.amazonaws.com/path/to/object | head -3
#    expect: HTTP/1.1 403 Forbidden

# 3. HTTP redirects to HTTPS (not plaintext)
curl -sI http://YOUR_DOMAIN/path/to/object | grep -i location
#    expect: a https:// Location header

# 4. Public Access Block is fully on
aws s3api get-public-access-block --bucket BUCKET
#    expect: all four flags true
```

If step 2 returns 200, the bucket is leaking — stop and fix the Public Access
Block + bucket policy before telling anyone it's done.

## Pitfalls

- **Website endpoint vs REST endpoint:** OAC requires the S3 *REST* endpoint
  (`bucket.s3.region.amazonaws.com`). The S3 *website* endpoint
  (`bucket.s3-website-...`) does NOT support OAC and forces the bucket public.
  If you need S3 website features (index docs, redirects), use a CloudFront
  Function / default root object instead of the website endpoint.
- **KMS-encrypted buckets:** OAC supports SSE-KMS (OAI did not). The KMS key
  policy must also allow the CloudFront service principal to `kms:Decrypt`.
- **403 after migration:** usually the bucket policy still trusts the old OAI,
  or the `AWS:SourceArn` distribution ID is wrong. Re-check both.
- **Default root object:** set `DefaultRootObject=index.html` for static sites,
  or `curl` to `/` returns 403/no-key errors.
- **Cache after updates:** changed an object but CDN serves stale? Invalidate:
  `aws cloudfront create-invalidation --distribution-id DIST_ID --paths "/*"`.

## References

See `references/distribution-config.json` for a complete, ready-to-edit
`create-distribution` config wired for an S3 origin + OAC + redirect-to-https.
