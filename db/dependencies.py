# db/dependencies.py
from .models import SessionLocal
from sqlalchemy.orm import Session


def get_db():
    """
    FastAPI Depends() ile kullanılan DB session factory.
    Her request başında session açar, bittikten sonra otomatik kapatır.
    Hata olsa bile finally bloğu sayesinde session her zaman kapatılır.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
