"""Agent pairing + presence.

The web app mints a short-lived pairing token; the user's local agent exchanges
it (once) for a long-lived device key it stores on disk, then heartbeats so the
dashboard can show "computer connected". No password ever leaves the browser."""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import User, AgentDevice
from server.auth import current_user, current_device, create_pairing_token, create_agent_key, _decode
from server.config import settings
from server.schemas import PairTokenOut, PairIn, PairOut, AgentStatusOut

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/pair-token", response_model=PairTokenOut)
def pair_token(request: Request, user: User = Depends(current_user)):
    """Web app: create a token to connect a new computer."""
    token = create_pairing_token(user.id)
    base = str(request.base_url).rstrip("/")
    # Terminal fallback (works with the cloned repo today). The packaged desktop
    # app will consume the same token via a deep link instead.
    command = f"SERVER_URL={base} AGENT_PAIR_TOKEN={token} python -m agent.agent"
    return PairTokenOut(token=token, expires_in_min=settings.pairing_token_ttl_min, command=command)


@router.post("/pair", response_model=PairOut)
def pair(body: PairIn, db: Session = Depends(get_db)):
    """Agent: exchange a pairing token for a durable device key."""
    err = HTTPException(400, "Invalid or expired pairing token")
    try:
        payload = _decode(body.token)
        if payload.get("scope") != "pair":
            raise err
        user_id = int(payload["sub"])
    except Exception:
        raise err
    if not db.get(User, user_id):
        raise err

    device = AgentDevice(user_id=user_id, name=body.device_name[:120] or "my computer",
                         last_seen=datetime.now(timezone.utc))
    db.add(device)
    db.commit()
    db.refresh(device)
    return PairOut(agent_key=create_agent_key(user_id, device.id), device_id=device.id)


@router.post("/heartbeat")
def heartbeat(dev=Depends(current_device), db: Session = Depends(get_db)):
    """Agent: mark this device online."""
    user, device_id = dev
    device = db.get(AgentDevice, device_id)
    if device and device.user_id == user.id:
        device.last_seen = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}


@router.get("/status", response_model=AgentStatusOut)
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Web app: is any of this user's computers currently connected?"""
    device = db.scalars(
        select(AgentDevice).where(AgentDevice.user_id == user.id, AgentDevice.last_seen.isnot(None))
        .order_by(AgentDevice.last_seen.desc()).limit(1)
    ).first()
    if not device or not device.last_seen:
        return AgentStatusOut(connected=False)
    last = device.last_seen
    if last.tzinfo is None:            # SQLite returns naive; Postgres tz-aware
        last = last.replace(tzinfo=timezone.utc)
    fresh = datetime.now(timezone.utc) - last < timedelta(seconds=settings.agent_online_secs)
    return AgentStatusOut(connected=fresh, device_name=device.name, last_seen=device.last_seen)
