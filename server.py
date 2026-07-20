"""
FastAPI server for InternHelper web UI.
Run: uvicorn server:app --reload --port 8000
"""
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import store
from browser_session import BrowserWorker

app = FastAPI(title="InternHelper")


@app.middleware("http")
async def no_cache_assets(request, call_next):
    """Don't let the browser cache the UI/assets — otherwise frontend changes
    silently don't show up until a manual hard refresh."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# One shared browser window, reused for every search and apply (see
# browser_session.BrowserWorker). Opened on first use, closed on demand.
_browser = BrowserWorker()

# ── Stores (résumés + applied-history persist to disk; jobs stay in memory) ────

# role -> { path, text, keywords, keyword_status }
_resumes: dict[str, dict] = store.load_resumes()

# url -> { title, company, applied_at } — listings already applied to
_applied: dict[str, dict] = store.load_applied()

# job_id -> { status, listings, error }
_jobs: dict[str, dict] = {}


def _mark_applied(listing: dict) -> None:
    """Record a successful application so we never re-apply to it."""
    _applied[listing["url"]] = {
        "title": listing.get("title", ""),
        "company": listing.get("company", ""),
        "role": listing.get("matched_role", ""),
        "stipend": listing.get("stipend", ""),
        "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    store.save_applied(_applied)

# Internshala login state: status is idle | logging_in | ready | error
_auth: dict = {"status": "idle", "error": None}


# ── Pydantic models ───────────────────────────────────────────────────────────

class MultiSearchParams(BaseModel):
    location: str = "work from home"
    stipend_min: int = 0
    max_per_role: int = 10
    platform: str | None = None  # which job platform; defaults to Internshala

class KeywordsUpdate(BaseModel):
    keywords: list[str]

class AnswerEdit(BaseModel):
    job_id: str
    listing_index: int
    answers: dict[str, str]
    action: str  # "approve" | "skip"

class BatchSubmit(BaseModel):
    job_id: str
    listing_indices: list[int]

class AppliedRemove(BaseModel):
    url: str


# ── Routes: UI ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("frontend/index.html", "r") as f:
        return f.read()


@app.get("/api/platforms")
async def platforms():
    from adapters import list_platforms
    return list_platforms()


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


@app.post("/api/login/{platform}")
async def login_platform(platform: str, background_tasks: BackgroundTasks):
    """Manual login for a platform (e.g. Unstop), preserving other logins."""
    from adapters import get_adapter
    adapter = get_adapter(platform)
    if not adapter.login_url:
        return JSONResponse({"error": f"{adapter.label} has no manual login."}, status_code=400)
    if _auth["status"] == "logging_in":
        return {"status": "logging_in"}
    _auth["status"] = "logging_in"
    _auth["error"] = None
    background_tasks.add_task(_platform_login_task, adapter.login_url)
    return {"status": "logging_in"}


# ── Routes: Browser window control ────────────────────────────────────────────

@app.get("/api/browser/status")
async def browser_status():
    return {"running": _browser.is_running()}


@app.post("/api/browser/close")
async def browser_close(background_tasks: BackgroundTasks):
    # Close in the background: if a task is mid-flight the window shuts down once
    # it finishes, so we don't block the request waiting on it.
    background_tasks.add_task(_browser.close)
    return {"ok": True}


# ── Routes: Applied history ───────────────────────────────────────────────────

@app.get("/api/applied")
async def list_applied():
    """Everything applied to, newest first."""
    items = [{"url": url, **data} for url, data in _applied.items()]
    items.sort(key=lambda x: x.get("applied_at", ""), reverse=True)
    return items


@app.post("/api/applied/remove")
async def remove_applied(body: AppliedRemove):
    """Forget one applied listing (it can then be applied to again)."""
    if body.url in _applied:
        del _applied[body.url]
        store.save_applied(_applied)
    return {"ok": True}


@app.delete("/api/applied")
async def clear_applied():
    _applied.clear()
    store.save_applied(_applied)
    return {"ok": True}


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
    store.save_resumes(_resumes)
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
    store.save_resumes(_resumes)
    return {"ok": True}


@app.patch("/api/resumes/{role}/keywords")
async def update_keywords(role: str, body: KeywordsUpdate):
    if role not in _resumes:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _resumes[role]["keywords"] = body.keywords
    store.save_resumes(_resumes)
    return {"ok": True}


@app.post("/api/resumes/{role}/retry-extract")
async def retry_extract(role: str, background_tasks: BackgroundTasks):
    if role not in _resumes:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _resumes[role]["keyword_status"] = "extracting"
    _resumes[role].pop("error", None)
    store.save_resumes(_resumes)
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


@app.post("/api/submit-batch")
async def submit_batch(body: BatchSubmit, background_tasks: BackgroundTasks):
    """Auto-apply to several no-question listings in one go. Only listings still
    eligible for auto-apply (status 'auto') are queued; each is applied in turn
    on the shared browser window."""
    job = _jobs.get(body.job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    queued: list[int] = []
    for idx in body.listing_indices:
        if 0 <= idx < len(job["listings"]):
            listing = job["listings"][idx]
            if listing.get("status") == "auto":
                listing["status"] = "submitting"
                listing["final_answers"] = {}
                queued.append(idx)

    if not queued:
        return JSONResponse({"error": "No auto-apply listings selected"}, status_code=400)

    job["batch"] = {"total": len(queued), "done": 0, "applied": 0, "failed": 0, "running": True}
    background_tasks.add_task(_run_submit_batch, body.job_id, queued)
    return {"ok": True, "count": len(queued)}


# ── Background tasks ──────────────────────────────────────────────────────────

def _relogin_task():
    """Open a headed browser, let the user solve the CAPTCHA, save the session."""
    try:
        import config as _config
        from playwright.sync_api import sync_playwright
        from auth.session import _login_with_captcha_pause

        # Re-login replaces the saved session, so the shared browser (built from
        # the old session) is stale — close it before logging in anew.
        _browser.close()

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


def _platform_login_task(login_url: str):
    """Open the platform's login page headed, wait for the user to finish, then
    save the combined session (preserving other platforms' logins)."""
    try:
        from playwright.sync_api import sync_playwright

        # Free the shared browser so login gets a clean, focused window.
        _browser.close()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            kwargs = {"storage_state": config.SESSION_PATH} if os.path.exists(config.SESSION_PATH) else {}
            context = browser.new_context(**kwargs)
            page = context.new_page()
            page.goto(login_url, wait_until="domcontentloaded")
            try:
                # Login is done once we leave the /login page.
                page.wait_for_url(lambda u: "/login" not in u.lower(), timeout=240_000)
                page.wait_for_timeout(3000)
            except Exception:
                pass
            context.storage_state(path=config.SESSION_PATH)
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
    finally:
        store.save_resumes(_resumes)  # persist text + keywords (or the error)


def _run_multi_search(job_id: str, params: MultiSearchParams):
    try:
        from adapters import get_adapter

        adapter = get_adapter(params.platform)
        seen_urls: set[str] = set()

        def work(context):
            listings: list[dict] = []
            for role, resume_data in _resumes.items():
                # Fall back to role name if LLM extraction didn't produce keywords
                keywords = " ".join(resume_data.get("keywords", [])) or role
                filters = {
                    "keywords": keywords,
                    "location": params.location,
                    "stipend_min": params.stipend_min,
                    "max_listings": params.max_per_role,
                }
                raw = adapter.search(context, filters)
                for r in raw:
                    if r["url"] in seen_urls:
                        continue
                    seen_urls.add(r["url"])

                    # Already applied in a past session? Show it as done and skip
                    # opening it — saves an Apply click (which risks throttling).
                    if r["url"] in _applied:
                        listings.append({
                            **r,
                            "platform": adapter.name,
                            "matched_role": role,
                            "resume_path": resume_data["path"],
                            "jd": "", "questions": [], "profile_incomplete": False,
                            "reason": f"Already applied on {_applied[r['url']].get('applied_at', '')[:10]}",
                            "status": "submitted",
                        })
                        continue

                    # Search-only platform (no auto-apply yet): hand off as a
                    # manual link without opening the listing.
                    if not adapter.supports_auto_apply:
                        listings.append({
                            **r,
                            "platform": adapter.name,
                            "matched_role": role,
                            "resume_path": resume_data["path"],
                            "jd": "", "questions": [], "profile_incomplete": False,
                            "reason": f"Apply on {adapter.label}",
                            "status": "link",
                        })
                        continue

                    # Pace classification so rapid Apply clicks don't get the
                    # platform session temporarily blocked.
                    time.sleep(config.SEARCH_CLASSIFY_DELAY)

                    # Open the listing to classify it: no custom questions -> we
                    # can auto-apply by uploading the résumé; questions (or an
                    # incomplete profile) -> hand back the direct link instead.
                    details = adapter.classify(context, r["url"])
                    questions = details.get("questions", [])
                    profile_incomplete = details.get("profile_incomplete", False)

                    if profile_incomplete:
                        status, reason = "link", "Complete your Internshala profile to apply"
                    elif questions:
                        status, reason = "link", f"{len(questions)} custom question(s) — apply manually"
                    else:
                        status, reason = "auto", ""

                    listings.append({
                        **r,
                        "platform": adapter.name,
                        "matched_role": role,
                        "resume_path": resume_data["path"],
                        "jd": details.get("jd", ""),
                        "questions": questions,
                        "profile_incomplete": profile_incomplete,
                        "reason": reason,
                        "status": status,
                    })
            return listings

        # Runs on the shared browser thread; the window stays open afterwards so
        # a following auto-apply reuses it instead of opening a new one.
        _jobs[job_id]["listings"] = _browser.run(work)
        _jobs[job_id]["status"] = "ready"
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = str(e)


def _run_submit_batch(job_id: str, indices: list[int]):
    """Apply to each queued listing in turn. Runs on the shared browser thread
    one at a time, so all applies reuse the single window/tab. Reports progress
    on the job and paces applies to avoid throttling."""
    from adapters import get_adapter

    job = _jobs.get(job_id)
    if not job:
        return
    batch = job["batch"]  # {total, done, applied, failed, running}
    for i, idx in enumerate(indices):
        listing = job["listings"][idx]
        adapter = get_adapter(listing.get("platform"))
        try:
            ok, msg = _browser.run(
                lambda context, l=listing, a=adapter: a.apply(context, l, l.get("final_answers") or {})
            )
            listing["status"] = "submitted" if ok else "error"
            if ok:
                _mark_applied(listing)
                batch["applied"] += 1
            else:
                listing["error"] = msg
                batch["failed"] += 1
        except Exception as e:
            listing["status"] = "error"
            listing["error"] = str(e)
            batch["failed"] += 1
        batch["done"] += 1

        # Pause between applications so a burst doesn't get the account flagged.
        if i < len(indices) - 1:
            time.sleep(config.APPLY_DELAY)

    batch["running"] = False


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
        from adapters import get_adapter

        listing = _jobs[job_id]["listings"][listing_index]
        adapter = get_adapter(listing.get("platform"))
        ok, msg = _browser.run(
            lambda context: adapter.apply(context, listing, listing["final_answers"])
        )
        listing["status"] = "submitted" if ok else "error"
        if ok:
            _mark_applied(listing)
        else:
            listing["error"] = msg
    except Exception as e:
        _jobs[job_id]["listings"][listing_index]["status"] = "error"
        _jobs[job_id]["listings"][listing_index]["error"] = str(e)
