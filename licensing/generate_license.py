#!/usr/bin/env python3
"""
KubePocket License Key Generator
==================================
Bu script SADECE sen kullanırsın. Private key gerektirir.
Asla production container'a veya repo'ya ekleme.

Kullanım:
    python generate_license.py --tier pro --customer "Acme Corp" --email admin@acme.com --months 12
    python generate_license.py --tier free --customer "Test User" --email test@example.com --months 1
"""

import argparse
import json
import base64
import sys
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization, hashes

TIER_DEFAULTS = {
    "free": {
        "cluster_limit":   1,
        "namespace_limit": 4,
        "retention_days":  30,
        "features":        ["metrics", "alerts", "anomaly", "forecast"],
    },
    "pro": {
        "cluster_limit": -1,
        "namespace_limit": -1,
        "retention_days":  365,
        "features":        ["metrics", "alerts", "anomaly", "forecast"],
    },
}


def generate_license(
    tier: str,
    customer: str,
    email: str,
    months: int,
    private_key_path: str,
    cluster_limit: int = None,
    namespace_limit: int = None,
    retention_days: int = None,
) -> str:
    key_path = Path(private_key_path)
    if not key_path.exists():
        print(f"❌ Private key not found: {key_path}", file=sys.stderr)
        sys.exit(1)

    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(), password=None)

    defaults = TIER_DEFAULTS.get(tier, TIER_DEFAULTS["free"])
    issued_at = date.today()
    expires_at = date.today() + timedelta(days=30 * months)

    payload = {
        "customer":        customer,
        "email":           email,
        "tier":            tier,
        "cluster_limit":   cluster_limit if cluster_limit is not None else defaults["cluster_limit"],
        "namespace_limit": namespace_limit if namespace_limit is not None else defaults["namespace_limit"],
        "retention_days":  retention_days if retention_days is not None else defaults["retention_days"],
        "features":        defaults["features"],
        "issued_at":       issued_at.isoformat(),
        "expires_at":      expires_at.isoformat(),
    }

    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    signature = private_key.sign(
        payload_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    license_key = f"kp_{payload_b64}.{signature_b64}"

    return license_key, payload


def main():
    parser = argparse.ArgumentParser(
        description="KubePocket License Key Generator")
    parser.add_argument("--tier",            required=True,
                        choices=["free", "pro"])
    parser.add_argument("--customer",        required=True)
    parser.add_argument("--email",           required=True)
    parser.add_argument("--months",          type=int, default=12)
    parser.add_argument("--private-key",     default="private_key.pem")
    parser.add_argument("--cluster-limit",   type=int, default=None)
    parser.add_argument("--namespace-limit", type=int, default=None)
    parser.add_argument("--retention-days",  type=int, default=None)
    parser.add_argument("--json",            action="store_true")
    args = parser.parse_args()

    license_key, payload = generate_license(
        tier=args.tier,
        customer=args.customer,
        email=args.email,
        months=args.months,
        private_key_path=args.private_key,
        cluster_limit=args.cluster_limit,
        namespace_limit=args.namespace_limit,
        retention_days=args.retention_days,
    )

    if args.json:
        print(json.dumps(
            {"license_key": license_key, "payload": payload}, indent=2))
    else:
        ns = "unlimited" if payload["namespace_limit"] == - \
            1 else payload["namespace_limit"]
        cls = "unlimited" if payload["cluster_limit"] == - \
            1 else payload["cluster_limit"]
        print("\n" + "="*60)
        print("KubePocket License Key")
        print("="*60)
        print(f"Customer:        {payload['customer']}")
        print(f"Email:           {payload['email']}")
        print(f"Tier:            {payload['tier'].upper()}")
        print(f"Cluster limit:   {cls}")
        print(f"Namespace limit: {ns}")
        print(f"Retention:       {payload['retention_days']} days")
        print(f"Features:        {', '.join(payload['features'])}")
        print(f"Issued:          {payload['issued_at']}")
        print(f"Expires:         {payload['expires_at']}")
        print("="*60)
        print(f"\nLicense Key:\n{license_key}\n")


if __name__ == "__main__":
    main()
