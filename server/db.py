"""SQLAlchemy engine + session (sync; runs in FastAPI's threadpool)."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from server.config import settings

# Railway gives postgres:// URLs; SQLAlchemy wants postgresql://
_url = settings.database_url.replace("postgres://", "postgresql://", 1)
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

# For the SQLite fallback, make sure its directory exists (else "unable to open").
if _url.startswith("sqlite"):
    _path = _url.split("sqlite:///", 1)[-1]
    if _path and os.path.dirname(_path):
        os.makedirs(os.path.dirname(_path), exist_ok=True)

engine = create_engine(_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a session, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from server import models  # noqa: F401  (register models)
    Base.metadata.create_all(bind=engine)
