"""Multi-tenant server ("brain") for InternHelper — Path B.

Accounts + per-user résumés/applications + the agent job queue. No browser here;
the Playwright work runs in each user's local agent (see agent/)."""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.db import init_db
from server.routers import auth, resumes, applications, jobs, actions, agent

init_db()  # create tables if missing (idempotent); Alembic migrations come later

app = FastAPI(title="InternHelper API")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/platforms")
def platforms():
    # Static here (the brain doesn't import the browser stack).
    return [
        {"name": "internshala", "label": "Internshala", "supports_auto_apply": True},
        {"name": "unstop", "label": "Unstop", "supports_auto_apply": True},
    ]


app.include_router(auth.router)
app.include_router(resumes.router)
app.include_router(applications.router)
app.include_router(jobs.router)
app.include_router(actions.router)
app.include_router(agent.router)

# ── Serve the dashboard ──────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(__file__))
_FRONTEND = os.path.join(_ROOT, "frontend")
app.mount("/static", StaticFiles(directory=os.path.join(_FRONTEND, "static")), name="static")
app.mount("/assets", StaticFiles(directory=os.path.join(_ROOT, "assets")), name="assets")


@app.middleware("http")
async def _no_cache(request, call_next):
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(_FRONTEND, "index.html"))
