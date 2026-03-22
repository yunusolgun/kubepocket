# api/auth.py
import hashlib
import secrets
import os
from datetime import datetime
from fastapi import Security, HTTPException, Depends
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from db.dependencies import get_db
from db.models import ApiKey

# Header name: requests must include "X-API-Key: kp_xxx..."
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# To disable auth entirely in development:
# KUBEPOCKET_DISABLE_AUTH=true  (never use in production!)
AUTH_DISABLED = os.getenv("KUBEPOCKET_DISABLE_AUTH", "false").lower() == "true"


def hash_key(raw_key: str) -> str:
    """
    Ham API key'i SHA256 ile hashle.
    Raw keys are never stored in the DB — only SHA256 hashes.
    An attacker with DB access cannot use the hashed keys.
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> str:
    """
    Generate a cryptographically secure random API key.
    Format: kp_ + 32 hex bytes = 'kp_a3f9...' (67 characters)
    The 'kp_' prefix distinguishes KubePocket keys from other secrets.
    """
    return f"kp_{secrets.token_hex(32)}"


def create_api_key(db: Session, name: str, expires_at: datetime = None) -> str:
    """
    Create a new API key and save its hash to the DB.
    Returns the raw key — visible only once, never shown again.
    """
    raw_key = generate_api_key()
    key_record = ApiKey(
        name=name,
        key_hash=hash_key(raw_key),
        expires_at=expires_at
    )
    db.add(key_record)
    db.commit()
    return raw_key


def get_current_key(
    raw_key: str = Security(API_KEY_HEADER),
    db: Session = Depends(get_db)
) -> ApiKey:
    """
    FastAPI dependency — added to every protected endpoint.
    Hashes the key from the header and looks it up in the DB.

    Returns the ApiKey object on success (use key.name in the
    endpoint to identify who made the request).
    Raises 401 on failure.
    """
    # Skip auth in development mode
    if AUTH_DISABLED:
        return ApiKey(name="dev-mode", key_hash="", is_active=True)

    # No header → 401
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Header: X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Look up the key hash in the DB
    key_record = db.query(ApiKey).filter(
        ApiKey.key_hash == hash_key(raw_key),
        ApiKey.is_active == True
    ).first()

    # Key not found
    if not key_record:
        raise HTTPException(
            status_code=401,
            detail="Invalid or inactive API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Check expiry
    if key_record.expires_at and key_record.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=401,
            detail="API key has expired",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Update last used timestamp for audit trail
    key_record.last_used_at = datetime.utcnow()
    db.commit()

    return key_record
