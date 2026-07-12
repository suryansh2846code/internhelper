"""
FastAPI server for InternHelper web UI.
Run: uvicorn server:app --reload --port 8000
"""
import os
import uuid
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="InternHelper")
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# ── In-memory stores ──────────────────────────────────────────────────────────

# role -> { path, text, keywords, keyword_status }
_resumes: dict[str, dict] = {}

# job_id -> { status, listings, error }
_jobs: dict[str, dict] = {}

# Internshala login state: status is idle | logging_in | ready | error
_auth: dict = {"status": "idle", "error": None}


# ── Pydantic models ───────────────────────────────────────────────────────────

class MultiSearchParams(BaseModel):
    location: str = "work from home"
    stipend_min: int = 0
    max_per_role: int = 10

class KeywordsUpdate(BaseModel):
    keywords: list[str]

class AnswerEdit(BaseModel):
    job_id: str
    listing_index: int
    answers: dict[str, str]
    action: str  # "approve" | "skip"


# ── Routes: UI ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("frontend/index.html", "r") as f:
        return f.read()


# ── Routes: Auth / session ────────────────────────────────────────────────────

@app.get("/api/auth/status")
async def auth_status():
    import config as _config
    return {**_auth, "has_session": os.path.exists(_config.SESSION_PATH)}


@app.post("/api/relogin")
async def relogin(background_tasks: BackgroundTasks):
    if _auth["status"] == "logging_in":
        return {"status": "logging_in"}
    _auth["status"] = "logging_in"
    _auth["error"] = None
    background_tasks.add_task(_relogin_task)
    return {"status": "logging_in"}


# ── Routes: Resume management ─────────────────────────────────────────────────

@app.post("/api/resumes")
async def upload_resume(
    background_tasks: BackgroundTasks,
    role: str = Form(...),
    file: UploadFile = File(...),
):
    ext = os.path.splitext(file.filename)[1]
    dest = f"./data/resumes/{role}{ext}"
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    _resumes[role] = {
        "path": dest,
        "filename": file.filename,
        "text": "",
        "keywords": [],
        "keyword_status": "extracting",  # extracting | ready | error
    }
    background_tasks.add_task(_extract_keywords_task, role)
    return {"ok": True, "role": role}


@app.get("/api/resumes")
async def list_resumes():
    return _resumes


@app.delete("/api/resumes/{role}")
async def delete_resume(role: str):
    if role not in _resumes:
        return JSONResponse({"error": "Not found"}, status_code=404)
    path = _resumes[role]["path"]
    if os.path.exists(path):
        os.remove(path)
    del _resumes[role]
    return {"ok": True}


@app.patch("/api/resumes/{role}/keywords")
async def update_keywords(role: str, body: KeywordsUpdate):
    if role not in _resumes:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _resumes[role]["keywords"] = body.keywords
    return {"ok": True}


@app.post("/api/resumes/{role}/retry-extract")
async def retry_extract(role: str, background_tasks: BackgroundTasks):
    if role not in _resumes:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _resumes[role]["keyword_status"] = "extracting"
    _resumes[role].pop("error", None)
    background_tasks.add_task(_extract_keywords_task, role)
    return {"ok": True}


# ── Routes: Search ────────────────────────────────────────────────────────────

@app.post("/api/search/multi")
async def start_multi_search(params: MultiSearchParams, background_tasks: BackgroundTasks):
    if not _resumes:
        return JSONResponse({"error": "Upload at least one resume first"}, status_code=400)
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "searching", "listings": [], "error": None}
    background_tasks.add_task(_run_multi_search, job_id, params)
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return job


# ── Routes: Generate & Submit ─────────────────────────────────────────────────

@app.post("/api/generate/{job_id}/{listing_index}")
async def generate_answers(job_id: str, listing_index: int, background_tasks: BackgroundTasks):
    job = _jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    job["listings"][listing_index]["status"] = "generating"
    background_tasks.add_task(_run_generate, job_id, listing_index)
    return {"ok": True}


@app.post("/api/submit")
async def submit_application(body: AnswerEdit, background_tasks: BackgroundTasks):
    job = _jobs.get(body.job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    listing = job["listings"][body.listing_index]
    if body.action == "skip":
        listing["status"] = "skipped"
        return {"ok": True}
    listing["final_answers"] = body.answers
    listing["status"] = "submitting"
    background_tasks.add_task(_run_submit, body.job_id, body.listing_index)
    return {"ok": True}


# ── Background tasks ──────────────────────────────────────────────────────────

def _relogin_task():
    """Open a headed browser, let the user solve the CAPTCHA, save the session."""
    try:
        import config as _config
        from playwright.sync_api import sync_playwright
        from auth.session import _login_with_captcha_pause

        if os.path.exists(_config.SESSION_PATH):
            os.remove(_config.SESSION_PATH)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context()
            _login_with_captcha_pause(context)
            context.storage_state(path=_config.SESSION_PATH)
            browser.close()

        _auth["status"] = "ready"
    except Exception as e:
        _auth["status"] = "error"
        _auth["error"] = str(e)


def _extract_keywords_task(role: str):
    try:
        from applicant.resume_parser import load_resume
        from applicant.keyword_extractor import extract_keywords
        import config

        resume_data = _resumes[role]
        text = load_resume(path=resume_data["path"])
        resume_data["text"] = text
        keywords = extract_keywords(text, role_hint=role)
        resume_data["keywords"] = keywords
        resume_data["keyword_status"] = "ready"
    except Exception as e:
        _resumes[role]["keyword_status"] = "error"
        _resumes[role]["error"] = str(e)


def _run_multi_search(job_id: str, params: MultiSearchParams):
    try:
        from playwright.sync_api import sync_playwright
        from auth.session import get_context
        from scraper.internshala import search_internships, get_listing_details

        seen_urls: set[str] = set()
        all_listings: list[dict] = []

        with sync_playwright() as pw:
            context = get_context(pw)

            for role, resume_data in _resumes.items():
                # Fall back to role name if LLM extraction didn't produce keywords
                keywords = " ".join(resume_data.get("keywords", [])) or role
                filters = {
                    "keywords": keywords,
                    "location": params.location,
                    "stipend_min": params.stipend_min,
                    "max_listings": params.max_per_role,
                }
                raw = search_internships(context, filters)
                for r in raw:
                    if r["url"] in seen_urls:
                        continue
                    seen_urls.add(r["url"])

                    # Open the listing to classify it: no custom questions -> we
                    # can auto-apply by uploading the résumé; questions (or an
                    # incomplete profile) -> hand back the direct link instead.
                    details = get_listing_details(context, r["url"])
                    questions = details.get("questions", [])
                    profile_incomplete = details.get("profile_incomplete", False)

                    if profile_incomplete:
                        status, reason = "link", "Complete your Internshala profile to apply"
                    elif questions:
                        status, reason = "link", f"{len(questions)} custom question(s) — apply manually"
                    else:
                        status, reason = "auto", ""

                    all_listings.append({
                        **r,
                        "matched_role": role,
                        "resume_path": resume_data["path"],
                        "jd": details.get("jd", ""),
                        "questions": questions,
                        "profile_incomplete": profile_incomplete,
                        "reason": reason,
                        "status": status,
                    })

            context.browser.close()

        _jobs[job_id]["listings"] = all_listings
        _jobs[job_id]["status"] = "ready"
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = str(e)


def _run_generate(job_id: str, listing_index: int):
    try:
        from applicant.resume_parser import load_resume
        from applicant.answer_generator import generate_answers
        import config as _config

        listing = _jobs[job_id]["listings"][listing_index]
        resume = load_resume(path=listing.get("resume_path") or _config.RESUME_PATH)

        answers = generate_answers(
            job_title=listing["title"],
            company=listing["company"],
            jd=listing["jd"],
            resume=resume,
            questions=listing["questions"],
        )
        listing["answers"] = answers
        listing["status"] = "ready"
    except Exception as e:
        _jobs[job_id]["listings"][listing_index]["status"] = "error"
        _jobs[job_id]["listings"][listing_index]["error"] = str(e)


def _run_submit(job_id: str, listing_index: int):
    try:
        from playwright.sync_api import sync_playwright
        from auth.session import get_context
        from apply.form_filler import submit_application

        listing = _jobs[job_id]["listings"][listing_index]
        with sync_playwright() as pw:
            context = get_context(pw)
            ok, msg = submit_application(context, listing, listing["final_answers"])
            context.browser.close()
        listing["status"] = "submitted" if ok else "error"
        if not ok:
            listing["error"] = msg
    except Exception as e:
        _jobs[job_id]["listings"][listing_index]["status"] = "error"
        _jobs[job_id]["listings"][listing_index]["error"] = str(e)
