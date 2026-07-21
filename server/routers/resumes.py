"""Per-user résumés: upload, list, delete, edit keywords.

Reuses the existing résumé parser + LLM keyword extractor from the monorepo."""
import os

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.config import settings
from server.db import get_db, SessionLocal
from server.models import User, Resume
from server.auth import current_user
from server.schemas import ResumeOut, KeywordsUpdate

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


def _extract_keywords_task(resume_id: int):
    """Parse the résumé and extract search keywords via the LLM (background)."""
    from applicant.resume_parser import load_resume
    from applicant.keyword_extractor import extract_keywords

    db = SessionLocal()
    try:
        r = db.get(Resume, resume_id)
        if not r:
            return
        try:
            text = load_resume(path=r.storage_path)
            r.text = text
            r.keywords = extract_keywords(text, role_hint=r.role)
            r.keyword_status = "ready"
        except Exception:
            r.keyword_status = "error"
        db.commit()
    finally:
        db.close()


@router.get("", response_model=list[ResumeOut])
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Resume).where(Resume.user_id == user.id)).all()


@router.post("", response_model=ResumeOut)
async def upload_resume(background: BackgroundTasks, role: str = Form(...), file: UploadFile = File(...),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    user_dir = os.path.join(settings.resume_dir, str(user.id))
    os.makedirs(user_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1]
    dest = os.path.join(user_dir, f"{role}{ext}")
    with open(dest, "wb") as f:
        f.write(await file.read())

    r = db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.role == role))
    if not r:
        r = Resume(user_id=user.id, role=role)
        db.add(r)
    r.filename = file.filename or ""
    r.storage_path = dest
    r.keyword_status = "extracting"
    r.keywords = []
    db.commit()
    db.refresh(r)
    background.add_task(_extract_keywords_task, r.id)
    return r


@router.patch("/{resume_id}/keywords", response_model=ResumeOut)
def update_keywords(resume_id: int, body: KeywordsUpdate,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Not found")
    r.keywords = body.keywords
    r.keyword_status = "ready"
    db.commit()
    db.refresh(r)
    return r


@router.get("/{resume_id}/file")
def download_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The user's agent fetches the résumé file to upload during apply."""
    r = db.get(Resume, resume_id)
    if not r or r.user_id != user.id or not os.path.exists(r.storage_path):
        raise HTTPException(404, "Not found")
    return FileResponse(r.storage_path, filename=r.filename or os.path.basename(r.storage_path))


@router.delete("/{resume_id}")
def delete_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if r and r.user_id == user.id:
        if r.storage_path and os.path.exists(r.storage_path):
            os.remove(r.storage_path)
        db.delete(r)
        db.commit()
    return {"ok": True}
