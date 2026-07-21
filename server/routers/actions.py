"""User-facing action endpoints that assemble jobs from the user's own data.

These complete the 'job wiring': the dashboard calls one endpoint, the server
builds the correct job payload (from the user's résumés etc.) and enqueues it
for the agent. Each returns the job id to poll."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import User, Resume, Job
from server.auth import current_user
from server.schemas import JobOut

router = APIRouter(prefix="/api", tags=["actions"])


class SearchRequest(BaseModel):
    platforms: list[str] | None = None
    location: str = "work from home"
    stipend_min: int = 0
    max_per_role: int = 10


class ApplyRequest(BaseModel):
    listing: dict
    resume_id: int | None = None


def _enqueue(db: Session, user_id: int, kind: str, payload: dict) -> Job:
    job = Job(user_id=user_id, kind=kind, payload=payload, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/search", response_model=JobOut)
def start_search(body: SearchRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Build a search job from the user's résumés (one 'role' per résumé)."""
    resumes = db.scalars(select(Resume).where(Resume.user_id == user.id)).all()
    roles = [{"role": r.role, "keywords": r.keywords or [], "resume_id": r.id} for r in resumes]
    payload = {
        "platforms": body.platforms,
        "location": body.location,
        "stipend_min": body.stipend_min,
        "max_per_role": body.max_per_role,
        "roles": roles,
    }
    return _enqueue(db, user.id, "search", payload)


@router.post("/apply", response_model=JobOut)
def start_apply(body: ApplyRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = {"listing": body.listing, "resume_id": body.resume_id}
    return _enqueue(db, user.id, "apply", payload)


@router.post("/sync", response_model=JobOut)
def start_sync(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _enqueue(db, user.id, "sync", {})
