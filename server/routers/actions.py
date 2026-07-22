"""User-facing action endpoints that assemble jobs from the user's own data.

These complete the 'job wiring': the dashboard calls one endpoint, the server
builds the correct job payload (from the user's résumés etc.) and enqueues it
for the agent. Each returns the job id to poll."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import User, Resume, Job, AgentProfile
from server.auth import current_user
from server.schemas import JobOut, ProfileOut, ProfileIn

router = APIRouter(prefix="/api", tags=["actions"])


class SearchRequest(BaseModel):
    platforms: list[str] | None = None
    location: str = "work from home"
    stipend_min: int = 0
    max_per_role: int = 10


class ApplyRequest(BaseModel):
    listing: dict
    resume_id: int | None = None
    answers: dict | None = None      # user's answers to custom questions (2nd pass)


class AnswerGenRequest(BaseModel):
    resume_id: int | None = None
    title: str = ""
    company: str = ""
    jd: str = ""
    questions: list[str] = []


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


def _apply_profile(db: Session, user_id: int) -> dict:
    p = db.scalar(select(AgentProfile).where(AgentProfile.user_id == user_id))
    return {"location": p.location, "course_duration": p.course_duration} if p else {}


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.scalar(select(AgentProfile).where(AgentProfile.user_id == user.id))
    return p or AgentProfile(user_id=user.id)


@router.put("/profile", response_model=ProfileOut)
def save_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.scalar(select(AgentProfile).where(AgentProfile.user_id == user.id))
    if not p:
        p = AgentProfile(user_id=user.id)
        db.add(p)
    p.location = body.location.strip()
    p.course_duration = body.course_duration.strip()
    db.commit()
    db.refresh(p)
    return p


@router.post("/apply", response_model=JobOut)
def start_apply(body: ApplyRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Inject the user's apply profile (city / course duration) so platforms like
    # Unstop that ask for it on every application can be auto-filled.
    payload = {"listing": body.listing, "resume_id": body.resume_id,
               "answers": body.answers or {}, "profile": _apply_profile(db, user.id)}
    return _enqueue(db, user.id, "apply", payload)


@router.post("/answers")
def generate_answers(body: AnswerGenRequest, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Draft answers to a listing's custom questions from the user's résumé + JD.

    Best-effort: if the LLM isn't configured or errors, returns blank drafts so
    the user can still type their own answers."""
    resume_text = ""
    if body.resume_id:
        r = db.get(Resume, body.resume_id)
        if r and r.user_id == user.id:
            resume_text = r.text or ""
    try:
        from applicant.answer_generator import generate_answers as _gen
        answers = _gen(body.title, body.company, body.jd, resume_text, body.questions)
    except Exception as e:
        print(f"[answers] generation failed: {e}", flush=True)
        answers = {q: "" for q in body.questions}
    return {"answers": answers}


@router.post("/sync", response_model=JobOut)
def start_sync(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _enqueue(db, user.id, "sync", {})
