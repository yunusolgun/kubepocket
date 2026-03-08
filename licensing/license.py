"""
KubePocket License System
=========================

Offline RSA-imzalı license key sistemi.

Key format:
    kp_<base64url(json_payload)>.<base64url(rsa_signature)>

Payload:
    {
        "customer": "acme-corp",
        "email": "admin@acme.com",
        "tier": "free|pro",
        "cluster_limit": 1,
        "namespace_limit": 4,
        "retention_days": 30,
        "features": ["anomaly", "forecast", "alerts"],
        "issued_at": "2026-03-01",
        "expires_at": "2027-03-01"
    }

Tier defaults:
    free:  1 cluster, 4 namespace, 30 gün retention, anomali+forecast+alerts
    pro:   unlimited her şey, tüm özellikler
"""

import json
import base64
from datetime import date, datetime
from typing import Optional
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.exceptions import InvalidSignature

# ── Public key (KubePocket içine gömülü) ─────────────────────────────────────
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1LErsPSwpOlEEXu6Zfhk
VY+K2eEWqhMXIr34PYZbPrNyWoW1OLp20tSZ/PnIol9Li9KP95f3CiMF+puPsb/d
Twr3V7ZOoTPUP5eqvd899GbuxZAfBrWu8++XL8rURO9ppJWZmCDQ/p/pjt70dItU
hvm0qN7Ylf60pGlzu9NOjgDQPf52sCQHCroK41Fi2tkRwAhrBYejVWAMKX9xDS7I
5kJZUP9emif0M6MT3EGMWu0GdpNA3u0W3KaTJr05yn4cNSlO0S4qFF3tYQoM1suZ
gc4DGnW54ruFlpIQxspZqr0jHGgyZzaEn9IGkFU/uLGvy1rflL2Ty/GvbkMj4pcv
QQIDAQAB
-----END PUBLIC KEY-----"""

# ── Tier tanımları ────────────────────────────────────────────────────────────
TIER_DEFAULTS = {
    "free": {
        "cluster_limit":   1,
        "namespace_limit": 4,
        "retention_days":  30,
        "features":        ["metrics", "alerts", "anomaly", "forecast"],
    },
    "pro": {
        "cluster_limit": -1,   # unlimited
        "namespace_limit": -1,   # unlimited
        "retention_days":  365,
        "features":        ["metrics", "alerts", "anomaly", "forecast"],
    },
}

# ── Dataclass ─────────────────────────────────────────────────────────────────


@dataclass
class LicenseInfo:
    valid:            bool
    tier:             str = "free"
    customer:         str = "community"
    email:            str = ""
    cluster_limit:    int = 1
    namespace_limit:  int = 4
    retention_days:   int = 30
    features:         list = field(default_factory=list)
    issued_at:        str = ""
    expires_at:       str = ""
    error:            str = ""

    def is_unlimited_namespaces(self) -> bool:
        return self.namespace_limit == -1

    def is_unlimited_clusters(self) -> bool:
        return self.cluster_limit == -1

    def has_feature(self, feature: str) -> bool:
        return feature in self.features

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = date.fromisoformat(self.expires_at)
            return date.today() > exp
        except ValueError:
            return False

    def days_until_expiry(self) -> Optional[int]:
        if not self.expires_at:
            return None
        try:
            exp = date.fromisoformat(self.expires_at)
            delta = (exp - date.today()).days
            return max(delta, 0)
        except ValueError:
            return None

    def to_dict(self) -> dict:
        return {
            "valid":             self.valid,
            "tier":              self.tier,
            "customer":          self.customer,
            "email":             self.email,
            "cluster_limit":     self.cluster_limit if self.cluster_limit != -1 else "unlimited",
            "namespace_limit":   self.namespace_limit if self.namespace_limit != -1 else "unlimited",
            "retention_days":    self.retention_days,
            "features":          self.features,
            "issued_at":         self.issued_at,
            "expires_at":        self.expires_at,
            "days_until_expiry": self.days_until_expiry(),
            "error":             self.error,
        }


# ── Community (ücretsiz, key yok) ─────────────────────────────────────────────
def _community_license() -> LicenseInfo:
    defaults = TIER_DEFAULTS["free"]
    return LicenseInfo(
        valid=True,
        tier="free",
        customer="community",
        features=defaults["features"],
        cluster_limit=defaults["cluster_limit"],
        namespace_limit=defaults["namespace_limit"],
        retention_days=defaults["retention_days"],
    )


# ── Key doğrulama ─────────────────────────────────────────────────────────────
def verify_license(license_key: Optional[str]) -> LicenseInfo:
    if not license_key or license_key.strip() == "":
        return _community_license()

    key = license_key.strip()
    if not key.startswith("kp_"):
        return LicenseInfo(valid=False, error="Invalid license key format (must start with kp_)")

    try:
        parts = key[3:].split(".")
        if len(parts) != 2:
            return LicenseInfo(valid=False, error="Invalid license key structure")

        payload_b64, signature_b64 = parts
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==")
        signature_bytes = base64.urlsafe_b64decode(signature_b64 + "==")

        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
        public_key.verify(
            signature_bytes,
            payload_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )

        payload = json.loads(payload_bytes.decode())
        tier = payload.get("tier", "free")
        defaults = TIER_DEFAULTS.get(tier, TIER_DEFAULTS["free"])

        info = LicenseInfo(
            valid=True,
            tier=tier,
            customer=payload.get("customer", ""),
            email=payload.get("email", ""),
            cluster_limit=payload.get(
                "cluster_limit",    defaults["cluster_limit"]),
            namespace_limit=payload.get(
                "namespace_limit", defaults["namespace_limit"]),
            retention_days=payload.get(
                "retention_days",  defaults["retention_days"]),
            features=payload.get("features",        defaults["features"]),
            issued_at=payload.get("issued_at", ""),
            expires_at=payload.get("expires_at", ""),
        )

        if info.is_expired():
            return LicenseInfo(
                valid=False,
                tier=tier,
                error=f"License expired on {info.expires_at}",
                expires_at=info.expires_at,
                customer=info.customer,
            )

        return info

    except InvalidSignature:
        return LicenseInfo(valid=False, error="Invalid license key signature")
    except Exception as e:
        return LicenseInfo(valid=False, error=f"License verification error: {e}")


# ── Limit kontrol yardımcıları ────────────────────────────────────────────────
def check_namespace_limit(license: LicenseInfo, namespace_count: int) -> tuple[bool, str]:
    if license.is_unlimited_namespaces():
        return True, ""
    if namespace_count > license.namespace_limit:
        return False, (
            f"Namespace limit reached ({namespace_count}/{license.namespace_limit}). "
            f"Upgrade to Pro for unlimited namespaces."
        )
    return True, ""


def check_feature(license: LicenseInfo, feature: str) -> tuple[bool, str]:
    if license.has_feature(feature):
        return True, ""
    return False, (
        f"Feature '{feature}' is not available on the {license.tier} tier. "
        f"Upgrade to Pro to access this feature."
    )


if __name__ == "__main__":
    import json as _json
    info = verify_license(None)
    print("Community license:")
    print(_json.dumps(info.to_dict(), indent=2))
