"""The agent job queue.

The dashboard enqueues work (search / apply / sync); the user's local agent
authenticates with the same account, atomically claims the next queued job,
runs it on their machine, and posts the result back."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import User, Job
from server.auth import current_user
from server.schemas import JobCreate, JobOut, JobResult
from server.routers.applications import upsert_applications

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=JobOut)
def enqueue(body: JobCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = Job(user_id=user.id, kind=body.kind, payload=body.payload, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[JobOut])
def my_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(50)
    ).all()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id:
        return JobOut(id=0, kind="", status="not_found", payload={}, result={}, error="")
    return job


# ── Agent-facing ────────────────────────────────────────────────────────────

@router.post("/claim", response_model=JobOut | None)
def claim_next(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Atomically hand the agent this user's next queued job (Postgres SKIP LOCKED)."""
    stmt = (select(Job)
            .where(Job.user_id == user.id, Job.status == "queued")
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True))
    job = db.scalars(stmt).first()
    if not job:
        return None
    job.status = "running"
    job.claimed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/result", response_model=JobOut)
def report_result(job_id: int, body: JobResult,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.user_id != user.id:
        return JobOut(id=0, kind="", status="not_found", payload={}, result={}, error="")
    job.status = body.status
    job.result = body.result
    job.error = body.error
    # Apply/sync jobs return applications to record for this user.
    apps = body.result.get("applications") if isinstance(body.result, dict) else None
    if apps:
        upsert_applications(db, user.id, apps)
    db.commit()
    db.refresh(job)
    return job
