"""
KubePocket License System
=========================

Offline RSA-signed license key system.

Key format:
    kp_<base64url(json_payload)>.<base64url(rsa_signature)>

Tier defaults:
    free:  1 cluster, 4 namespaces, 30 days retention, metrics+alerts+anomaly+forecast
    pro:   unlimited everything, all features, 365 days retention

Community (no key):
    Same limits as free tier, with a 30-day trial period tracked in PostgreSQL.
    After 30 days the system continues to work but returns trial_expired=True.

Pro expired:
    Falls back to free tier limits with pro_expired=True warning.
    Existing data is NOT deleted — only new collection is limited to 4 namespaces.
    Retention cleanup only affects data newer than the downgrade date.
"""

import json
import base64
from datetime import date, datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.exceptions import InvalidSignature

PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1LErsPSwpOlEEXu6Zfhk
VY+K2eEWqhMXIr34PYZbPrNyWoW1OLp20tSZ/PnIol9Li9KP95f3CiMF+puPsb/d
Twr3V7ZOoTPUP5eqvd899GbuxZAfBrWu8++XL8rURO9ppJWZmCDQ/p/pjt70dItU
hvm0qN7Ylf60pGlzu9NOjgDQPf52sCQHCroK41Fi2tkRwAhrBYejVWAMKX9xDS7I
5kJZUP9emif0M6MT3EGMWu0GdpNA3u0W3KaTJr05yn4cNSlO0S4qFF3tYQoM1suZ
gc4DGnW54ruFlpIQxspZqr0jHGgyZzaEn9IGkFU/uLGvy1rflL2Ty/GvbkMj4pcv
QQIDAQAB
-----END PUBLIC KEY-----"""

TRIAL_DAYS = 30

# ── Immutable tier constants ─────────────────────────────────────────────────
# These values are hardcoded and cannot be changed at runtime.
# Do NOT replace these with variables or make them configurable —
# they define the hard limits of the Free tier.
_FREE_CLUSTER_LIMIT   = 1
_FREE_NAMESPACE_LIMIT = 4
_FREE_RETENTION_DAYS  = 30
_FREE_FEATURES        = ("metrics", "alerts", "anomaly", "forecast")

_PRO_CLUSTER_LIMIT    = -1   # unlimited
_PRO_NAMESPACE_LIMIT  = -1   # unlimited
_PRO_RETENTION_DAYS   = 365
_PRO_FEATURES         = ("metrics", "alerts", "anomaly", "forecast")

# Read-only view used by generate_license.py and other tooling.
# Never use this dict to enforce limits at runtime — use the constants above.
TIER_DEFAULTS = {
    "free": {
        "cluster_limit":   _FREE_CLUSTER_LIMIT,
        "namespace_limit": _FREE_NAMESPACE_LIMIT,
        "retention_days":  _FREE_RETENTION_DAYS,
        "features":        list(_FREE_FEATURES),
    },
    "pro": {
        "cluster_limit":   _PRO_CLUSTER_LIMIT,
        "namespace_limit": _PRO_NAMESPACE_LIMIT,
        "retention_days":  _PRO_RETENTION_DAYS,
        "features":        list(_PRO_FEATURES),
    },
}


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
    # Trial fields (community only)
    is_trial:         bool = False
    trial_started_at: str = ""
    trial_expires_at: str = ""
    trial_expired:    bool = False
    trial_days_left:  Optional[int] = None
    # Pro expired downgrade
    pro_expired:      bool = False
    pro_expired_at:   str = ""

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
            return date.today() >= date.fromisoformat(self.expires_at)
        except ValueError:
            return False

    def days_until_expiry(self) -> Optional[int]:
        if not self.expires_at:
            return None
        try:
            delta = (date.fromisoformat(self.expires_at) - date.today()).days
            return max(delta, 0)
        except ValueError:
            return None

    def to_dict(self) -> dict:
        d = {
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
        if self.is_trial:
            d["trial"] = {
                "active": not self.trial_expired,
                "started_at": self.trial_started_at,
                "expires_at": self.trial_expires_at,
                "days_left":  self.trial_days_left,
                "expired":    self.trial_expired,
            }
        if self.pro_expired:
            d["pro_expired"] = {
                "expired_at": self.pro_expired_at,
                "message": (
                    f"Your Pro license expired on {self.pro_expired_at}. "
                    "You have been downgraded to the Free tier. "
                    "Existing data is preserved — renew Pro to regain full access."
                ),
            }
        return d


# ── Trial helpers ─────────────────────────────────────────────────────────────
def _get_or_create_trial() -> tuple[datetime, bool]:
    try:
        from db.models import SessionLocal, TrialInfo
        db = SessionLocal()
        try:
            trial = db.query(TrialInfo).filter(TrialInfo.id == 1).first()
            if trial is None:
                trial = TrialInfo(id=1, started_at=datetime.utcnow())
                db.add(trial)
                db.commit()
                db.refresh(trial)
            started_at = trial.started_at
            expired = datetime.utcnow() > started_at + timedelta(days=TRIAL_DAYS)
            return started_at, expired
        finally:
            db.close()
    except Exception:
        return datetime.utcnow(), False


def _community_license() -> LicenseInfo:
    started_at, expired = _get_or_create_trial()
    expires_at = started_at + timedelta(days=TRIAL_DAYS)
    days_left = max((expires_at.date() - date.today()).days,
                    0) if not expired else 0

    return LicenseInfo(
        valid=True,
        tier="free",
        customer="community",
        features=list(_FREE_FEATURES),
        cluster_limit=_FREE_CLUSTER_LIMIT,
        namespace_limit=_FREE_NAMESPACE_LIMIT,
        retention_days=_FREE_RETENTION_DAYS,
        is_trial=True,
        trial_started_at=started_at.date().isoformat(),
        trial_expires_at=expires_at.date().isoformat(),
        trial_expired=expired,
        trial_days_left=days_left,
    )


def _expired_pro_fallback(customer: str, email: str, expires_at: str) -> LicenseInfo:
    """
    Pro license expired — fall back to free tier limits.
    Data is NOT deleted. Retention cleanup will only apply to data
    collected after the expiry date.
    """
    return LicenseInfo(
        valid=True,
        tier="free",
        customer=customer,
        email=email,
        features=list(_FREE_FEATURES),
        cluster_limit=_FREE_CLUSTER_LIMIT,
        namespace_limit=_FREE_NAMESPACE_LIMIT,
        retention_days=_FREE_RETENTION_DAYS,
        expires_at=expires_at,
        pro_expired=True,
        pro_expired_at=expires_at,
    )


# ── Key verification ──────────────────────────────────────────────────────────
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

        # Use hardcoded constants as fallback — never trust TIER_DEFAULTS at runtime
        if tier == "pro":
            _def_cl, _def_nl, _def_rd, _def_ft = _PRO_CLUSTER_LIMIT, _PRO_NAMESPACE_LIMIT, _PRO_RETENTION_DAYS, list(_PRO_FEATURES)
        else:
            _def_cl, _def_nl, _def_rd, _def_ft = _FREE_CLUSTER_LIMIT, _FREE_NAMESPACE_LIMIT, _FREE_RETENTION_DAYS, list(_FREE_FEATURES)

        info = LicenseInfo(
            valid=True,
            tier=tier,
            customer=payload.get("customer", ""),
            email=payload.get("email", ""),
            cluster_limit=payload.get("cluster_limit",    _def_cl),
            namespace_limit=payload.get("namespace_limit", _def_nl),
            retention_days=payload.get("retention_days",  _def_rd),
            features=payload.get("features",              _def_ft),
            issued_at=payload.get("issued_at", ""),
            expires_at=payload.get("expires_at", ""),
        )

        # Expired pro → soft downgrade to free (data preserved)
        if info.is_expired() and tier == "pro":
            return _expired_pro_fallback(
                customer=info.customer,
                email=info.email,
                expires_at=info.expires_at,
            )

        # Expired free key → invalid
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


# ── Limit helpers ─────────────────────────────────────────────────────────────
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
