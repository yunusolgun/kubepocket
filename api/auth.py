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

# Header adı: istek yaparken "X-API-Key: kp_xxx..." şeklinde gönderilir
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Geliştirme ortamında auth'u tamamen devre dışı bırakmak için:
# KUBEPOCKET_DISABLE_AUTH=true  (asla production'da kullanma!)
AUTH_DISABLED = os.getenv("KUBEPOCKET_DISABLE_AUTH", "false").lower() == "true"


def hash_key(raw_key: str) -> str:
    """
    Ham API key'i SHA256 ile hashle.
    DB'de düz key saklanmaz — sadece hash tutulur.
    Saldırgan DB'ye erişse bile key'leri kullanamaz.
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> str:
    """
    Kriptografik olarak güvenli random key üret.
    Format: kp_ + 32 byte hex = 'kp_a3f9...' (67 karakter)
    'kp_' prefix'i key'i diğer secret'lardan ayırt etmeyi sağlar.
    """
    return f"kp_{secrets.token_hex(32)}"


def create_api_key(db: Session, name: str, expires_at: datetime = None) -> str:
    """
    Yeni API key oluştur, hash'ini DB'ye kaydet.
    Ham key'i döndürür — sadece bu anda görünür, bir daha gösterilmez!
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
    FastAPI dependency — korumalı her endpoint'e eklenir.
    Header'daki key'i hash'leyip DB'de arar.

    Başarılı olursa ApiKey nesnesini döndürür (endpoint'te
    key.name ile kimin istek yaptığını görebilirsin).
    Başarısız olursa 401 fırlatır.
    """
    # Geliştirme modunda auth atla
    if AUTH_DISABLED:
        return ApiKey(name="dev-mode", key_hash="", is_active=True)

    # Header yoksa 401
    if not raw_key:
        raise HTTPException(
            status_code=401,
            detail="API key gerekli. Header: X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Hash'i DB'de ara
    key_record = db.query(ApiKey).filter(
        ApiKey.key_hash == hash_key(raw_key),
        ApiKey.is_active == True
    ).first()

    # Key bulunamadı
    if not key_record:
        raise HTTPException(
            status_code=401,
            detail="Geçersiz veya deaktif API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Süresi dolmuş mu?
    if key_record.expires_at and key_record.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=401,
            detail="API key süresi dolmuş",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Son kullanım zamanını güncelle (kim, ne zaman kullandı takibi)
    key_record.last_used_at = datetime.utcnow()
    db.commit()

    return key_record
