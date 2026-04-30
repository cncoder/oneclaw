#!/usr/bin/env python3.12
"""Publish podcast MP3 + HTML player to S3/CloudFront (PRIVATE bucket only).

SECURITY CONTRACT (non-negotiable):
- Bucket is PRIVATE: Public Access Block fully ON, BucketOwnerEnforced.
- Objects are PRIVATE: no public ACLs, no `acl: public-read`.
- Access path: CloudFront → Origin Access Control (OAC) → S3.
- Bucket policy grants s3:GetObject ONLY to the specific CloudFront distribution.
- Script REFUSES to run against a bucket whose Public Access Block is not fully ON.

Usage:
    # 1) Check environment (AWS creds + cached config)
    python3.12 publish_to_cdn.py check

    # 2) Provision a private bucket + CloudFront (first-time setup, ~15 min)
    python3.12 publish_to_cdn.py provision \\
        --bucket my-private-podcast-cdn --region us-east-1
    # (config is cached to ~/.podcast-generator/publish.json)

    # 3) Publish an episode — uses cached bucket/domain by default
    python3.12 publish_to_cdn.py publish \\
        --mp3 /tmp/demo.mp3 --html /tmp/demo_player.html \\
        --slug ai-vs-programmers \\
        [--bucket BUCKET] [--cloudfront-domain d123.cloudfront.net]

The first run on a new machine must go through `provision` — this skill does NOT
hardcode any bucket or CloudFront domain. The returned CloudFront URL is what
you share.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# AWS helpers (lazy imports so `check` can report a friendly error)
# ---------------------------------------------------------------------------

def _boto():
    try:
        import boto3  # noqa: F401
    except ImportError:
        print("ERROR: boto3 not installed. Run: pip3.12 install boto3", file=sys.stderr)
        sys.exit(2)
    import boto3
    return boto3


def _check_creds() -> dict | None:
    b = _boto()
    try:
        sts = b.client("sts")
        return sts.get_caller_identity()
    except Exception as e:
        print(f"ERROR: AWS credentials not usable: {e}", file=sys.stderr)
        print("Fix options:", file=sys.stderr)
        print("  1) Run: aws configure", file=sys.stderr)
        print("  2) Or export: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION",
              file=sys.stderr)
        print("  3) Or use a named profile: export AWS_PROFILE=...", file=sys.stderr)
        return None


_BUCKET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def _validate_bucket_name(name: str) -> None:
    """Raise ValueError if name violates S3 bucket naming rules."""
    if not _BUCKET_NAME_RE.match(name):
        raise ValueError(
            f"Invalid bucket name {name!r}. Rules: 3-63 chars, lowercase letters/digits/"
            "hyphens/dots only, must start and end with letter or digit."
        )
    if ".." in name or ".-" in name or "-." in name:
        raise ValueError(f"Invalid bucket name {name!r}: no consecutive dots or dot-hyphen.")
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", name):
        raise ValueError(f"Invalid bucket name {name!r}: cannot look like an IP address.")


# ---------------------------------------------------------------------------
# Public-access safety gate
# ---------------------------------------------------------------------------

def _assert_bucket_private(s3, bucket: str) -> None:
    """Fail hard if bucket is not fully private. This is the iron rule."""
    try:
        pab = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    except s3.exceptions.ClientError as e:
        raise RuntimeError(
            f"Bucket {bucket!r}: cannot read Public Access Block ({e}). "
            "REFUSING to upload — configure PAB to all-True first."
        ) from e
    required = {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    bad = {k: pab.get(k) for k, v in required.items() if pab.get(k) is not v}
    if bad:
        raise RuntimeError(
            f"Bucket {bucket!r} is not fully private (PAB mismatch: {bad}). "
            "REFUSING to upload. All four block-public flags must be True."
        )

    # Verify bucket policy does not grant Principal:* unconditionally.
    try:
        pol = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        for st in pol.get("Statement", []):
            if st.get("Effect") != "Allow":
                continue
            p = st.get("Principal")
            if p == "*" or (isinstance(p, dict) and p.get("AWS") == "*"):
                # Acceptable only if restricted by aws:SourceArn to a CloudFront distribution.
                cond = st.get("Condition", {})
                src = (
                    cond.get("StringEquals", {}).get("AWS:SourceArn")
                    or cond.get("ArnEquals", {}).get("AWS:SourceArn")
                    or cond.get("StringEquals", {}).get("aws:SourceArn")
                )
                if not src or "cloudfront" not in str(src).lower():
                    raise RuntimeError(
                        f"Bucket {bucket!r} policy has an unrestricted Principal:*. "
                        "REFUSING to upload. Only CloudFront OAC access permitted."
                    )
    except s3.exceptions.from_code("NoSuchBucketPolicy"):
        pass  # no bucket policy — fine (PAB already enforces)
    except Exception as e:
        # Be paranoid: if we can't verify the policy, refuse.
        raise RuntimeError(f"Bucket {bucket!r}: policy check failed ({e}). REFUSING.") from e


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


def _content_type(path: Path) -> str:
    ct = _CONTENT_TYPES.get(path.suffix.lower())
    if ct:
        return ct
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _upload_object(s3, bucket: str, key: str, path: Path) -> None:
    # Explicitly NO ACL param → bucket-owner-enforced keeps it private.
    s3.upload_file(
        str(path), bucket, key,
        ExtraArgs={
            "ContentType": _content_type(path),
            "CacheControl": "public, max-age=300" if path.suffix == ".html" else "public, max-age=31536000",
        },
    )


# ---------------------------------------------------------------------------
# Provisioning a new private bucket + CloudFront distribution (OAC)
# ---------------------------------------------------------------------------

def provision(bucket: str, region: str = "us-east-1") -> dict:
    """Create a PRIVATE bucket + CloudFront distribution with OAC.

    Returns metadata dict with distribution ID and domain.
    Idempotent where possible (skips existing resources).
    """
    _validate_bucket_name(bucket)
    b = _boto()
    s3 = b.client("s3", region_name=region)
    cf = b.client("cloudfront")
    sts = b.client("sts")
    account = sts.get_caller_identity()["Account"]

    # 1) Create bucket (private by default; explicitly enforce object ownership)
    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        print(f"[provision] created bucket s3://{bucket}")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        print(f"[provision] bucket s3://{bucket} already exists (owned by you)")
    except s3.exceptions.BucketAlreadyExists:
        raise RuntimeError(f"Bucket name {bucket!r} already taken globally. Pick another.")

    # 2) Enforce ownership + Public Access Block
    s3.put_bucket_ownership_controls(
        Bucket=bucket,
        OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
    )
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    print("[provision] PAB fully ON + BucketOwnerEnforced")

    # 3) Create Origin Access Control
    oac_name = f"{bucket}-oac"
    oac_id = None
    for oac in cf.list_origin_access_controls().get("OriginAccessControlList", {}).get("Items", []):
        if oac["Name"] == oac_name:
            oac_id = oac["Id"]
            break
    if not oac_id:
        resp = cf.create_origin_access_control(
            OriginAccessControlConfig={
                "Name": oac_name,
                "Description": f"OAC for {bucket}",
                "SigningProtocol": "sigv4",
                "SigningBehavior": "always",
                "OriginAccessControlOriginType": "s3",
            },
        )
        oac_id = resp["OriginAccessControl"]["Id"]
        print(f"[provision] created OAC {oac_id}")
    else:
        print(f"[provision] reusing OAC {oac_id}")

    # 4) Create CloudFront distribution (HTTPS only, redirect HTTP→HTTPS)
    origin_domain = f"{bucket}.s3.{region}.amazonaws.com"
    caller_ref = f"pgen-{bucket}-{int(time.time())}"
    dist_config = {
        "CallerReference": caller_ref,
        "Comment": f"podcast-generator private CDN for {bucket}",
        "Enabled": True,
        "Origins": {
            "Quantity": 1,
            "Items": [{
                "Id": "s3-origin",
                "DomainName": origin_domain,
                "OriginAccessControlId": oac_id,
                "S3OriginConfig": {"OriginAccessIdentity": ""},
                "CustomHeaders": {"Quantity": 0},
                "OriginPath": "",
                "ConnectionAttempts": 3,
                "ConnectionTimeout": 10,
            }],
        },
        "DefaultCacheBehavior": {
            "TargetOriginId": "s3-origin",
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 2, "Items": ["GET", "HEAD"],
                "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
            },
            "Compress": True,
            "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",  # Managed-CachingOptimized
        },
        "PriceClass": "PriceClass_100",
        "HttpVersion": "http2",
        "IsIPV6Enabled": True,
        "DefaultRootObject": "index.html",
    }
    resp = cf.create_distribution(DistributionConfig=dist_config)
    dist = resp["Distribution"]
    dist_id = dist["Id"]
    dist_arn = dist["ARN"]
    dist_domain = dist["DomainName"]
    print(f"[provision] created CloudFront {dist_id} → {dist_domain}")

    # 5) Bucket policy: allow only this distribution
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowCloudFrontServicePrincipal",
            "Effect": "Allow",
            "Principal": {"Service": "cloudfront.amazonaws.com"},
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{bucket}/*",
            "Condition": {"StringEquals": {"AWS:SourceArn": dist_arn}},
        }],
    }
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
    print("[provision] bucket policy scoped to this CloudFront distribution only")

    return {
        "bucket": bucket,
        "region": region,
        "account": account,
        "distribution_id": dist_id,
        "cloudfront_domain": dist_domain,
    }


# ---------------------------------------------------------------------------
# Publish flow
# ---------------------------------------------------------------------------

@dataclass
class PublishResult:
    mp3_url: str | None
    html_url: str | None
    bucket: str
    prefix: str


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def publish(
    *,
    mp3: Path,
    html: Path | None,
    slug: str,
    bucket: str,
    cloudfront_domain: str | None,
    prefix: str = "podcast",
    date: str | None = None,
    rewrite_html_mp3_src: bool = True,
) -> PublishResult:
    b = _boto()
    s3 = b.client("s3")

    ident = _check_creds()
    if ident is None:
        sys.exit(2)
    print(f"[publish] AWS account {ident['Account']} / {ident['Arn']}")

    # Hard gate: bucket must be fully private.
    _assert_bucket_private(s3, bucket)
    print(f"[publish] bucket {bucket!r} is verified PRIVATE")

    if date and not _DATE_RE.match(date):
        raise ValueError(f"--date must be YYYY-MM-DD, got {date!r}")
    if not date:
        date = time.strftime("%Y-%m-%d")
    slug_safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug).strip("-") or "episode"

    base_key = f"{prefix.strip('/')}/{date}/{slug_safe}"
    mp3_key = f"{base_key}/podcast.mp3"
    html_key = f"{base_key}/index.html" if html else None

    # Upload MP3 first
    if not mp3.exists():
        raise FileNotFoundError(f"MP3 not found: {mp3}")
    _upload_object(s3, bucket, mp3_key, mp3)
    print(f"[publish] MP3  -> s3://{bucket}/{mp3_key}")

    # Prepare HTML (optionally rewrite <source src="..."> to relative `podcast.mp3`)
    html_url = None
    if html:
        if not html.exists():
            raise FileNotFoundError(f"HTML not found: {html}")
        if rewrite_html_mp3_src:
            original = html.read_text(encoding="utf-8")
            patched = re.sub(
                r'(<source\s+src=")[^"]+(")',
                r'\1podcast.mp3\2',
                original,
                count=1,
            )
            if patched != original:
                tmp = html.with_suffix(".s3.html")
                tmp.write_text(patched, encoding="utf-8")
                _upload_object(s3, bucket, html_key, tmp)
                tmp.unlink(missing_ok=True)
            else:
                _upload_object(s3, bucket, html_key, html)
        else:
            _upload_object(s3, bucket, html_key, html)
        print(f"[publish] HTML -> s3://{bucket}/{html_key}")

    def _url(key: str) -> str:
        if cloudfront_domain:
            return f"https://{cloudfront_domain.strip('/')}/{key}"
        # Fallback: S3 path URL (will 403 unless signed — warn the user).
        return f"s3://{bucket}/{key}  (no CloudFront domain configured)"

    mp3_url = _url(mp3_key)
    html_url = _url(html_key) if html_key else None

    print("-" * 50)
    print(f"  MP3:  {mp3_url}")
    if html_url:
        print(f"  HTML: {html_url}  ← share this link")
    print("-" * 50)

    return PublishResult(mp3_url=mp3_url, html_url=html_url, bucket=bucket, prefix=base_key)


# ---------------------------------------------------------------------------
# Config cache — remembers the user's private bucket + CloudFront domain.
# Path: ~/.podcast-generator/publish.json  (per-user, never committed)
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path.home() / ".podcast-generator" / "publish.json"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_config(data: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Environment check
# ---------------------------------------------------------------------------

def check_env() -> int:
    b = _boto()
    ident = _check_creds()
    if ident is None:
        print("  No AWS credentials available. Fix with `aws configure` or set env vars.")
        return 1
    print(f"  AWS: OK — account {ident['Account']}, arn {ident['Arn']}")

    cfg = _load_config()
    bucket = cfg.get("bucket")
    domain = cfg.get("cloudfront_domain")

    if not bucket:
        print(f"  Cached config:  none (at {_CONFIG_PATH})")
        print()
        print("  Not ready. First-time setup:")
        print("    python3.12 publish_to_cdn.py provision --bucket YOUR-UNIQUE-BUCKET-NAME")
        print()
        print("  Or publish one-off with explicit flags:")
        print("    python3.12 publish_to_cdn.py publish --bucket B --cloudfront-domain D ...")
        return 0

    print(f"  Cached bucket:       s3://{bucket}")
    print(f"  Cached CloudFront:   {domain or '(none)'}")

    s3 = b.client("s3")
    try:
        s3.head_bucket(Bucket=bucket)
        _assert_bucket_private(s3, bucket)
        print(f"  Public Access Block: OK (fully private)")
        print()
        print("  READY TO PUBLISH:")
        print("    python3.12 publish_to_cdn.py publish \\")
        print("      --mp3 podcast.mp3 --html player.html --slug my-episode")
    except Exception as e:
        print(f"  Bucket check FAILED: {e}")
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="Check AWS creds + existing private bucket readiness")

    pp = sub.add_parser("publish", help="Upload MP3 + HTML to an existing PRIVATE bucket")
    pp.add_argument("--mp3", type=Path, required=True)
    pp.add_argument("--html", type=Path, default=None, help="Optional HTML player")
    pp.add_argument("--slug", required=True, help="Episode slug (e.g. ai-vs-programmers)")
    pp.add_argument("--bucket", default=None,
                    help="Override cached bucket (default: ~/.podcast-generator/publish.json)")
    pp.add_argument("--cloudfront-domain", default=None,
                    help="Override cached CloudFront domain")
    pp.add_argument("--prefix", default="podcast")
    pp.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    pp.add_argument("--no-rewrite", action="store_true",
                    help="Don't patch HTML <source src> to relative podcast.mp3")

    pv = sub.add_parser("provision", help="Create a NEW private bucket + CloudFront (OAC)")
    pv.add_argument("--bucket", required=True)
    pv.add_argument("--region", default="us-east-1")

    args = ap.parse_args()

    if args.cmd == "check":
        return check_env()

    if args.cmd == "provision":
        meta = provision(bucket=args.bucket, region=args.region)
        _save_config({
            "bucket": meta["bucket"],
            "region": meta["region"],
            "cloudfront_domain": meta["cloudfront_domain"],
            "distribution_id": meta["distribution_id"],
        })
        print(json.dumps(meta, indent=2))
        print(f"\nConfig cached to {_CONFIG_PATH}")
        print("CloudFront is provisioning (5-15 min). Once Deployed=true, run:")
        print("  python3.12 publish_to_cdn.py publish --mp3 ... --html ... --slug ...")
        return 0

    if args.cmd == "publish":
        cfg = _load_config()
        bucket = args.bucket or cfg.get("bucket")
        domain = args.cloudfront_domain or cfg.get("cloudfront_domain")
        if not bucket:
            print("ERROR: no bucket configured. Run `publish_to_cdn.py provision --bucket ...` "
                  "or pass --bucket explicitly.", file=sys.stderr)
            return 2
        try:
            publish(
                mp3=args.mp3,
                html=args.html,
                slug=args.slug,
                bucket=bucket,
                cloudfront_domain=domain,
                prefix=args.prefix,
                date=args.date,
                rewrite_html_mp3_src=not args.no_rewrite,
            )
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
