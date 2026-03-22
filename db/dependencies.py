# db/dependencies.py
from .models import SessionLocal
from sqlalchemy.orm import Session


def get_db():
    """
    DB session factory used with FastAPI Depends().
    Opens a session at the start of each request and closes it when done.
    The finally block ensures the session is always closed, even on error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
