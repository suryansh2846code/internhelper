"""Per-user applications (the manager) — now DB-backed and isolated per user."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import User, Application
from server.auth import current_user
from server.schemas import ApplicationOut, StatusUpdate

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _norm(u: str) -> str:
    return (u or "").split("?")[0].rstrip("/")


@router.get("", response_model=list[ApplicationOut])
def list_applications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Application).where(Application.user_id == user.id).order_by(Application.applied_at.desc())
    ).all()


@router.post("/{app_id}/status")
def set_status(app_id: int, body: StatusUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.get(Application, app_id)
    if app and app.user_id == user.id:
        app.status = body.status
        db.commit()
    return {"ok": True}


@router.delete("/{app_id}")
def remove(app_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.get(Application, app_id)
    if app and app.user_id == user.id:
        db.delete(app)
        db.commit()
    return {"ok": True}


@router.delete("")
def clear(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(Application).where(Application.user_id == user.id))
    db.commit()
    return {"ok": True}


def upsert_applications(db: Session, user_id: int, items: list[dict]) -> tuple[int, int]:
    """Merge synced/applied items into a user's applications (add or update status)."""
    existing = {_norm(a.url): a for a in db.scalars(
        select(Application).where(Application.user_id == user_id)).all()}
    added = updated = 0
    for it in items:
        key = _norm(it.get("url", ""))
        if not key:
            continue
        if key in existing:
            new_status = it.get("status")
            if new_status and new_status != existing[key].status:
                existing[key].status = new_status
                updated += 1
        else:
            db.add(Application(
                user_id=user_id, url=it["url"], title=it.get("title", ""),
                company=it.get("company", ""), role=it.get("role", ""),
                stipend=it.get("stipend", ""), platform=it.get("platform", ""),
                status=it.get("status", "applied"),
                applied_at=datetime.now(timezone.utc),
            ))
            added += 1
    db.commit()
    return added, updated
