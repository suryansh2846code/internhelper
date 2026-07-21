"""Multi-tenant server ("brain") for InternHelper — Path B.

Accounts + per-user résumés/applications + the agent job queue. No browser here;
the Playwright work runs in each user's local agent (see agent/)."""
from fastapi import FastAPI

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
