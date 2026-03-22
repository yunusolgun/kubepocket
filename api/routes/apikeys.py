# api/routes/apikeys.py
from pydantic import BaseModel
from api.auth import create_api_key, get_current_key
from db.models import ApiKey
from db.dependencies import get_db
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


router = APIRouter()


# --- Request / Response modelleri ---

class CreateKeyRequest(BaseModel):
    name: str                           # e.g. "prod-dashboard", "github-actions"
    expires_at: Optional[datetime] = None


class CreateKeyResponse(BaseModel):
    id: int
    name: str
    key: str                            # RAW KEY — visible only in this response!
    created_at: datetime
    expires_at: Optional[datetime] = None


class KeyInfoResponse(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    # key_hash intentionally excluded


# --- Endpoints ---

@router.post("/", response_model=CreateKeyResponse)
def create_key(
    request: CreateKeyRequest,
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)  # This endpoint is also protected
):
    """
    Create a new API key.
    WARNING: Save the returned 'key' immediately — it will not be shown again.
    """
    raw_key = create_api_key(db, name=request.name,
                             expires_at=request.expires_at)

    # Fetch the newly created record to get its id
    from db.models import ApiKey as ApiKeyModel
    from api.auth import hash_key
    record = db.query(ApiKeyModel).filter(
        ApiKeyModel.key_hash == hash_key(raw_key)
    ).first()

    return CreateKeyResponse(
        id=record.id,
        name=record.name,
        key=raw_key,           # Shown only once here
        created_at=record.created_at,
        expires_at=record.expires_at
    )


@router.get("/", response_model=List[KeyInfoResponse])
def list_keys(
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """List all API keys (hashes are never returned)."""
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [
        KeyInfoResponse(
            id=k.id,
            name=k.name,
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at
        )
        for k in keys
    ]


@router.delete("/{key_id}")
def revoke_key(
    key_id: int,
    db: Session = Depends(get_db),
    _auth: ApiKey = Depends(get_current_key)
):
    """Deactivate an API key (not deleted — preserved for audit trail)."""
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()

    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    key.is_active = False
    db.commit()

    return {"status": "revoked", "id": key_id, "name": key.name}
