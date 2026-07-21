"""Multi-tenant server ("brain") for InternHelper — Path B.

Accounts + per-user résumés/applications + the agent job queue. No browser here;
the Playwright work runs in each user's local agent (see agent/)."""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.db import init_db
from server.routers import auth, resumes, applications, jobs, actions

init_db()  # create tables if missing (idempotent); Alembic migrations come later

app = FastAPI(title="InternHelper API")


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(auth.router)
app.include_router(resumes.router)
app.include_router(applications.router)
app.include_router(jobs.router)
app.include_router(actions.router)

# ── Serve the dashboard ──────────────────────────────────────────────────────
_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(_FRONTEND, "static")), name="static")


@app.middleware("http")
async def _no_cache(request, call_next):
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(_FRONTEND, "index.html"))
