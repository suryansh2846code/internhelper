"""Per-user résumés: upload, list, delete, edit keywords.

Files are stored as bytes in the DB (stateless — safe on ephemeral hosts).
Keyword extraction reuses the existing parser + LLM via a temp file."""
import os
import tempfile

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db import get_db, SessionLocal
from server.models import User, Resume
from server.auth import current_user
from server.schemas import ResumeOut, KeywordsUpdate

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


def _extract_keywords_task(resume_id: int, ext: str):
    """Parse the résumé bytes and extract keywords via the LLM (background)."""
    from applicant.resume_parser import load_resume
    from applicant.keyword_extractor import extract_keywords

    db = SessionLocal()
    try:
        r = db.get(Resume, resume_id)
        if not r or not r.content:
            return
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext or ".pdf")
        try:
            tmp.write(r.content)
            tmp.close()
            text = load_resume(path=tmp.name)
            r.text = text
            r.keywords = extract_keywords(text, role_hint=r.role)
            r.keyword_status = "ready"
        except Exception:
            r.keyword_status = "error"
        finally:
            os.unlink(tmp.name)
        db.commit()
    finally:
        db.close()


@router.get("", response_model=list[ResumeOut])
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Resume).where(Resume.user_id == user.id)).all()


@router.post("", response_model=ResumeOut)
async def upload_resume(background: BackgroundTasks, role: str = Form(...), file: UploadFile = File(...),
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = await file.read()
    ext = os.path.splitext(file.filename or "")[1]

    r = db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.role == role))
    if not r:
        r = Resume(user_id=user.id, role=role)
        db.add(r)
    r.filename = file.filename or ""
    r.content = data
    r.keyword_status = "extracting"
    r.keywords = []
    db.commit()
    db.refresh(r)
    background.add_task(_extract_keywords_task, r.id, ext)
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
    if not r or r.user_id != user.id or not r.content:
        raise HTTPException(404, "Not found")
    return Response(r.content, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{r.filename or "resume"}"'})


@router.delete("/{resume_id}")
def delete_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if r and r.user_id == user.id:
        db.delete(r)
        db.commit()
    return {"ok": True}
