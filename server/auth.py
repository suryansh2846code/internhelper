"""Password hashing, JWT issue/verify, and the current-user dependency."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from server.config import settings
from server.db import get_db
from server.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(pw: str) -> str:
    # bcrypt only uses the first 72 bytes
    return bcrypt.hashpw(pw.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def _encode(claims: dict, ttl_min: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=ttl_min)
    return jwt.encode({**claims, "exp": exp}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_token(user_id: int) -> str:
    """Web-session token (from email/password login)."""
    return _encode({"sub": str(user_id)}, settings.access_token_ttl_min)


def create_pairing_token(user_id: int) -> str:
    """Short-lived token the web app hands out to pair a new device."""
    return _encode({"sub": str(user_id), "scope": "pair"}, settings.pairing_token_ttl_min)


def create_agent_key(user_id: int, device_id: int) -> str:
    """Long-lived key a paired agent stores locally and uses for all calls."""
    return _encode({"sub": str(user_id), "scope": "agent", "device": device_id},
                   settings.agent_key_ttl_min)


def _decode(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Accepts web-session tokens and agent keys (not bare pairing tokens)."""
    creds_err = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                             headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = _decode(token)
        if payload.get("scope") == "pair":
            raise creds_err  # pairing tokens can't access the API directly
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise creds_err
    user = db.get(User, user_id)
    if not user:
        raise creds_err
    return user


def current_device(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Require an agent key; returns (User, device_id) for heartbeats."""
    creds_err = HTTPException(status.HTTP_401_UNAUTHORIZED, "Agent key required",
                             headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = _decode(token)
        if payload.get("scope") != "agent":
            raise creds_err
        user_id = int(payload["sub"])
        device_id = int(payload["device"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise creds_err
    user = db.get(User, user_id)
    if not user:
        raise creds_err
    return user, device_id
