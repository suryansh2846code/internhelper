"""SQLAlchemy engine + session (sync; runs in FastAPI's threadpool)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from server.config import settings

# Railway gives postgres:// URLs; SQLAlchemy wants postgresql://
_url = settings.database_url.replace("postgres://", "postgresql://", 1)
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

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
