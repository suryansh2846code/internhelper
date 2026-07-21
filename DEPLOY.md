# Deploying the server (Railway)

The **server** ("brain") is deployed; the **agent** runs on each user's machine.

## 1. Railway setup
1. New project → **Deploy from GitHub repo** (branch `path-b-multitenant`).
2. Add a **PostgreSQL** plugin. Railway injects `DATABASE_URL` automatically.
3. Railway detects the `Dockerfile` and builds the lean server image
   (`requirements-server.txt` — no Playwright).

## 2. Environment variables
Set these in the Railway service:

| Var | Notes |
|-----|-------|
| `DATABASE_URL` | provided by the Postgres plugin |
| `JWT_SECRET`   | a long random string (required in prod) |
| `LLM_PROVIDER` | `groq` \| `openai` \| `anthropic` |
| `GROQ_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | the one matching the provider |

Tables are created automatically on boot (`init_db`). Alembic migrations later.

## 3. The agent (each user, local)
```bash
pip install -r requirements.txt        # full deps (Playwright)
playwright install chromium
SERVER_URL=https://<your>.up.railway.app \
  AGENT_EMAIL=you@example.com AGENT_PASSWORD=... \
  python -m agent.agent
```
The agent logs into the platforms locally (headed, solve any CAPTCHA once) and
polls the server for jobs. Résumé files are stored in Postgres, so the server
is stateless and safe on Railway's ephemeral disk.
