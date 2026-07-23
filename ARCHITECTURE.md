# InternHelper — How Everything Works

A complete map of the system: architecture, data, APIs, every flow, the adapters,
packaging/distribution, and a release runbook. Read this to understand *how* the
app does what it does. (For the chronological "why we built it this way" journal,
see `PROJECT.md`; for hosting, `DEPLOY.md`; for building the apps, `packaging/BUILD.md`.)

---

## 1. The big idea (Path-B split: brain + hands)

InternHelper finds internships and auto-applies to them across **Internshala** and
**Unstop**. It's split into two halves so a user's platform passwords and browsing
never touch our server:

- **The "brain" — the server** (`server/`): a FastAPI web app. Holds accounts,
  résumés, applications, per-user settings, and a **job queue**. **No browser runs
  here.** Deployed once (Railway). Also serves the dashboard UI (`frontend/`).
- **The "hands" — the agent** (`agent/`): a small program that runs on the **user's
  own computer**. It logs into the platforms *there* (their session, their IP),
  polls the server for queued work, runs it locally with Playwright, and posts
  results back.

The only link between them is the job queue over HTTPS. The connection is
**one-way**: the agent polls out to the server (the server can't reach into the
user's machine). This is why "pause/stop" is cooperative and why a "restart" can't
be pushed remotely.

```
Browser (dashboard)  ──HTTPS──►  Server / brain  ◄──HTTPS(poll)──  Agent / hands
   user clicks               (accounts, queue)                 (Playwright, logins)
                                                                on the user's PC
```

---

## 2. Repository layout

| Path | What it is |
|---|---|
| `server/` | The brain: FastAPI app, DB models, routers, auth. |
| `server/main.py` | App entry; mounts routers, `/static`, `/assets`; serves `index.html`. |
| `server/routers/` | HTTP endpoints (see §4). |
| `server/models.py` | SQLAlchemy tables (see §3). |
| `agent/` | The hands: job loop, pairing, menu-bar app, browser session. |
| `agent/agent.py` | Core: connect/pair, job handlers (`search`/`apply`/`sync`), `run_agent`. |
| `agent/app.py` | macOS menu-bar app (rumps) around the same core. |
| `agent/session.py` | Persistent browser profile + platform login helpers. |
| `agent/client.py` | Thin HTTP client the agent uses to talk to the server. |
| `adapters/` | Platform-specific logic behind one interface (`base.py`). |
| `scraper/internshala.py` | Internshala scraping (search, details, apply form). |
| `apply/form_filler.py` | Internshala apply-form filling + `run_apply` + eligibility check. |
| `applicant/` | Résumé parsing, keyword extraction, answer generation (LLM). |
| `browser_session.py` | `BrowserWorker`: one long-lived Playwright browser, single reused tab. |
| `frontend/` | The dashboard (vanilla HTML/CSS/JS). |
| `packaging/` | PyInstaller specs + build scripts for the downloadable apps. |
| `.github/workflows/build-windows.yml` | CI that builds the Windows `.exe`. |
| `config.py` | Runtime config for the agent/scraper (env-driven; `.env` optional). |

---

## 3. Data model (`server/models.py`)

All rows are per-user (multi-tenant). Tables are created by `init_db()` /
`create_all` on startup (new tables appear automatically; **column changes need a
migration** — that's why new per-user settings were added as *new tables*).

- **users** — `id, email, password_hash, created_at`.
- **resumes** — one per role: `role, filename, content (bytes), text, keywords (JSON),
  keyword_status (extracting|ready|error)`. Files live in the DB (stateless host-safe).
- **applications** — recorded applies/syncs: `url, title, company, role, stipend,
  platform, status, applied_at`.
- **agent_profiles** — per-user apply details Unstop asks for every time:
  `location, course_duration`. Injected into apply jobs.
- **agent_controls** — run controls the agent honours: `paused (bool), stop_seq (int)`.
- **agent_devices** — paired computers: `name, last_seen` (heartbeats → "online").
- **jobs** — the work queue: `kind (search|apply|sync), status (queued|running|
  done|failed), payload (JSON), result (JSON), error, created_at, claimed_at`.

---

## 4. HTTP API (by router, all under `/api`)

**auth** (`routers/auth.py`) — `POST /auth/register`, `POST /auth/login` (returns JWT).
Every other endpoint requires the JWT (web) or the device key (agent); both resolve
to a user via `current_user`.

**resumes** (`routers/resumes.py`)
- `GET /resumes`, `POST /resumes` (upload; kicks off background keyword extraction),
  `PATCH /resumes/{id}/keywords`, `DELETE /resumes/{id}`, `GET /resumes/{id}/file`
  (agent downloads the file to upload during apply). Add/delete is locked (409) while
  a search/apply job is active.

**actions** (`routers/actions.py`) — user-facing "do something" endpoints that build
a job from the user's data and enqueue it:
- `POST /search` — builds a `search` job (one "role" per résumé, with its keywords).
- `POST /apply` — builds an `apply` job for one listing; injects the apply profile.
- `POST /sync` — builds a `sync` job.
- `POST /answers` — LLM-drafts answers to a listing's custom questions (résumé + JD).
- `GET/PUT /profile` — the apply profile (city / course duration).

**jobs** (`routers/jobs.py`) — the queue:
- `GET /jobs/{id}` — the dashboard polls this for a job's status/result.
- `POST /jobs/claim` — **agent** atomically claims the next queued job
  (Postgres `SKIP LOCKED`). Returns nothing if the user is paused.
- `POST /jobs/{id}/result` — **agent** reports `done`/`failed` + result; apply/sync
  results carry `applications` which get recorded.

**agent** (`routers/agent.py`) — pairing, presence, controls:
- `POST /agent/pair-token` (web) → short-lived pairing code + `server_url` +
  `download_mac`/`download_windows`.
- `POST /agent/pair` (agent) → exchanges the code for a durable device key.
- `POST /agent/heartbeat` (agent) → marks the device online.
- `GET /agent/status` (web) → `{connected, device_name, paused}`.
- `POST /agent/pause` · `POST /agent/resume` · `POST /agent/stop` (web).
- `GET /agent/control` (agent) → `{paused, stop_seq}`, read between listings.

---

## 5. The job queue (how work flows)

1. Dashboard calls an **actions** endpoint → a `Job` row is inserted `queued`.
2. The dashboard **polls** `GET /jobs/{id}` every ~2s for status.
3. The agent loop (`run_job_loop`) **claims** the next queued job (unless paused),
   runs the matching handler, and **reports** the result.
4. The dashboard sees `done`/`failed` and renders.

**Job kinds & handlers** (`agent/agent.py`):
- `search` → `handle_search`
- `apply` → `handle_apply`
- `sync` → `handle_sync`

**Time limits** (so nothing hangs the UI): search 480s, apply 180s, sync 180s. On
timeout the handler returns/raises a clear message instead of blocking.

**Pause / Stop:**
- *Pause*: `claim` returns nothing while `agent_controls.paused` is true (the agent
  keeps heartbeating, just takes no work).
- *Stop*: bumps `stop_seq` and cancels queued jobs; a running **search** checks
  `stop_seq` between listings and aborts. Bulk apply is stopped in the browser (the
  loop breaks after the current listing).

---

## 6. End-to-end flows

### 6.1 Onboarding / connecting a computer
1. User registers / logs in.
2. Uploads one résumé per role → server extracts keywords via the LLM (background).
3. Sets the **apply profile** (city, course duration) in Search settings.
4. Clicks **Connect your computer** → the wizard (`connectComputer`) fetches a
   pairing code and walks them through: **pick OS → download & open the app (or the
   terminal path) → paste the code → log into the platforms once**. It polls
   `GET /agent/status` and flips to a green "✓ Connected" screen automatically.
5. The agent pairs (`/agent/pair`), saves a device key at `~/.internhelper/agent.json`,
   downloads Chromium on first run, and opens the platform login pages (with an
   on-page **InternHelper banner**) for a one-time sign-in.

### 6.2 Search (rate-limit-safe)
`handle_search` → for each platform × role it calls `adapter.search()` (list) and,
for each listing, `adapter.fetch_details()` which **only reads** the listing page
(full JD, stipend, duration, skills, perks). **It never clicks "Apply" during
search** — that was the original rate-limiting cause. Every auto-apply listing comes
back with `status: "auto"`.

### 6.3 Apply (on-demand, with question handling)
Clicking **Apply** enqueues an `apply` job → `adapter.try_apply()`:
- No custom questions → submit → recorded as an application.
- **Custom questions** → returns `needs_answers` + the questions (no blank submit).
  The dashboard opens an answers modal, calls `POST /answers` to draft answers from
  the résumé + JD, the user edits, and a second `apply` call submits with answers.
- **Not eligible / applications closed / deadline passed / already applied** →
  `ineligibility_reason()` surfaces a clear message instead of a vague failure.
- **Profile incomplete / not logged in / rate-limited** → each its own message.

For Internshala this is a **single form load** (`run_apply` checks for questions and
submits in one pass). For Unstop the same wizard both fills profile fields and
detects/answers questions.

### 6.4 Bulk apply
"Auto-apply to all" runs the selected `auto` listings **one at a time**, paced ~4s
apart. Listings that turn out to have questions are **skipped and flagged**
(`✍️N need answers`) for the user to answer individually — nothing goes out with
unreviewed AI text. A **Stop** button breaks the loop after the current listing.

### 6.5 Sync
`handle_sync` reads each platform's "my applications" page and merges live statuses
(applied / under review / interview / offer / rejected) into the user's list.

---

## 7. Adapters (`adapters/`)

One interface (`base.py`) so adding a platform = writing one adapter:
- `search(context, filters)` → list of `{url, title, company, stipend, logo, …}`.
- `fetch_details(context, url)` → rich detail dict (JD, skills, meta) — **no apply
  click**. Default: `{}`.
- `classify(context, url)` → apply-time probe (questions / profile / login).
- `apply(context, listing, answers)` → `(ok, message)`.
- `try_apply(context, listing, answers)` → `{ok, message, needs_answers?, questions?,
  jd?}` — the agent-facing apply that surfaces questions.

**Internshala** (`adapters/internshala.py` + `scraper/internshala.py` +
`apply/form_filler.py`): keyword-URL search; `get_listing_info` scrapes details;
`run_apply` does the single-pass apply (option questions auto-answered, custom
textareas detected, résumé uploaded, submit confirmed).

**Unstop** (`adapters/unstop.py`): searches the public JSON API (details ride along —
JD, skills, location, deadline). Apply drives the multi-step register wizard: fills
**location** (typed + autocomplete suggestion, with a keyboard fallback), **course
duration** (radio by value or label), **skills**, ticks **all** required agreement
checkboxes, detects custom questions, and submits. Location & course duration come
from the **apply profile** (injected into the job), falling back to env vars for the
CLI.

---

## 8. Agent internals

- **`BrowserWorker`** (`browser_session.py`): sync Playwright is thread-affine, so one
  dedicated thread owns the browser and runs every task from a queue (serialized).
  It keeps **exactly one reused tab** (`_install_single_tab`) so automation stays in
  one quiet window and never spawns tabs. It self-heals if the window is closed.
  → *Consequence:* login and jobs share one tab, so the agent logs in **before**
  starting the job loop (otherwise a running search would navigate the login page away).
- **Persistent profile** (`agent/session.py` `open_profile`): a headed, on-disk
  Chromium profile so platform logins persist across runs. `open_login_page` stamps
  an InternHelper banner on the login page.
- **Chromium bootstrap** (`agent/_bootstrap.py`): Chromium isn't bundled (bundling the
  pre-signed browser breaks code-signing); it's downloaded to the user's cache on
  first run.
- **Pairing / identity**: device key stored at `~/.internhelper/agent.json`; re-runs
  reconnect without re-pairing. `_connect` resolves: saved key → `AGENT_PAIR_TOKEN`
  env → email/password → **interactive prompt** (for the packaged/console app).

---

## 9. Frontend (`frontend/`)

Vanilla JS. `auth.js` handles the JWT and lazy-loads `app.js`. Key pieces:
- **Connect wizard** — step-by-step (pick OS → guided steps → live "Connected ✓"),
  with per-OS commands (bash / PowerShell / cmd) and Download buttons when the
  packaged apps are published.
- **Listing cards** — bright tiles; whole card opens a **detail modal** painted in the
  card's colour; a single **⚡ Apply** button; a **Select** checkbox for bulk.
- **Answers modal** — AI-drafted answers to custom questions, editable, then submit.
- **Run controls** — Pause/Resume (sidebar), Stop (bulk bar & during search).
- Asset versions are cache-busted via `?v=N` in `index.html`/`auth.js`.

Static assets are served from **`/static`** (illustrations live in
`frontend/static/illustration/` — the `/assets` mount 404'd on the deploy, so they
were moved).

---

## 10. Packaging & distribution

The agent can run three ways: (a) run-from-source terminal, (b) packaged macOS app,
(c) packaged Windows app. Chromium downloads on first run in all cases.

- **macOS** (`packaging/build_mac.sh`, `InternHelperAgent.spec`, `run_agent_app.py`):
  a menu-bar app (`rumps`). `bash packaging/build_mac.sh` → `dist/InternHelperAgent.zip`.
  Sign + notarize for distribution (see `packaging/BUILD.md`).
- **Windows** (`InternHelperAgent-win.spec`, `run_agent_win.py`): a **console app** —
  run it, paste the code when prompted. Built on CI:
  `.github/workflows/build-windows.yml` (Actions → Run workflow, or push a `v*` tag)
  produces `InternHelperAgent-windows.zip`.
- `--check` on either binary validates the bundled Playwright driver **and** the full
  search/apply import path (catches missing deps like `rich`/`dotenv` at build time).

**Wiring the Download buttons:** set server env vars to the published release asset
URLs — `AGENT_DOWNLOAD_MAC`, `AGENT_DOWNLOAD_WINDOWS`. When set, the wizard shows a
Download button for that OS; otherwise it shows the terminal path.

---

## 11. Deployment (server)

- Hosted on **Railway** from the **`main`** branch (`Dockerfile` → `uvicorn
  server.main:app`). Postgres is injected as `DATABASE_URL` (SQLite locally).
- Key env vars: `DATABASE_URL`, `JWT_SECRET`, `AGENT_DOWNLOAD_MAC`,
  `AGENT_DOWNLOAD_WINDOWS`, LLM keys for keyword/answer generation.
- `main` and `path-b-multitenant` are kept in sync (identical). `git clone` fetches
  the **default branch**, so agent files must be on `main` — they are.
- Redeploy after code or env-var changes. The **agent** must be restarted separately
  to pick up agent-side code (the server can't push code to it).

---

## 12. Design decisions worth remembering

- **No Apply click during search** → the single biggest rate-limiting fix; question
  detection moved to apply time, on demand, one listing at a time.
- **Single-pass apply** → one Internshala form load per apply (halves clicks vs.
  check-then-submit), important for bulk throttle safety.
- **New tables, not new columns**, for per-user settings → `create_all` picks them up
  without a migration.
- **Login before the job loop** → the single reused tab can't be shared between a
  manual login and a running search.
- **Cooperative controls** → pause/stop work over the poll channel; there's no inbound
  channel to the user's machine.

---

## 13. Release runbook

1. `git tag vX.Y.Z && git push origin vX.Y.Z` → CI builds & attaches the Windows zip
   to the GitHub Release.
2. `bash packaging/build_mac.sh` → (sign/notarize) → upload `InternHelperAgent.zip`
   to the same release.
3. Copy both asset URLs → set `AGENT_DOWNLOAD_MAC` / `AGENT_DOWNLOAD_WINDOWS` on
   Railway → redeploy.
4. Verify: Connect wizard shows Download buttons; download → open → paste code →
   "Connected ✓".

---

## 14. Known limitations / gotchas

- **Agent code updates need a manual restart / rebuild** (no auto-update yet).
- **Unsigned apps** warn on Gatekeeper (mac) / SmartScreen (Windows) until signed.
- **Course-duration** uses Unstop's opaque radio values; matched by value or label,
  falls back to the first option.
- **Frontend keyword search** can't exclude adjacent roles (e.g. "full stack" under a
  "frontend" search) — by design the user decides per listing.
- **Chromium first-run download** is ~150 MB.
