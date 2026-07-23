# InternHelper — The Full Journey

Everything about this project from the ground up: what it is, how it grew, and a
**problem → cause → solution** log of every issue we hit and how we fixed it (with
the commit that did it). If `ARCHITECTURE.md` is "how it works today," this is "how
we got here and why."

---

## Part 0 — What InternHelper is (the basics)

A tool that **finds internships and auto-applies to them** on **Internshala** and
**Unstop**.

- You upload a résumé per role (frontend, backend, …). It extracts search keywords.
- It searches the platforms, shows the listings, and can **auto-apply** — filling the
  application form, answering custom questions, uploading your résumé, and submitting.
- The tricky constraint: applying has to happen **as you**, logged into your own
  account, from your own machine — we never want your platform passwords on a server.

That constraint shaped the entire architecture.

---

## Part 1 — The starting point: a single-user script

The first version was a local Python app: one user, credentials in a `.env`,
Playwright driving a browser, an LLM writing answers to custom questions, and a
small review UI. It worked for one person on one machine, but it couldn't be a
product: everyone would need the code, the env vars, and their passwords sitting in
a file.

Core pieces from that era that still exist today:
- `scraper/internshala.py` — search + read a listing + reach the apply form.
- `apply/form_filler.py` — fill and submit the Internshala form.
- `applicant/` — résumé parsing, keyword extraction, answer generation (LLM).
- `browser_session.py` — one long-lived browser, reused.

---

## Part 2 — The rearchitecture: "Path B" (brain + hands)

To make it a real multi-user product **without ever holding platform passwords**, we
split it in two:

- **Brain (server)** — accounts, résumés, applications, settings, and a **job queue**.
  No browser. Deployed once.
- **Hands (agent)** — runs on *each user's* computer, logs into the platforms there,
  polls the queue, runs the work locally, reports back.

They talk only through the job queue, and only the agent initiates contact (it polls
out). This is the defining decision of the project.

This landed over several phases:
- **Auth + multi-tenant server** — accounts, JWT, per-user tables (`131fedc`, `5e8c4b9`).
- **Action endpoints that build jobs from user data** (`79742f2`).
- **Stateless résumé storage** so it survives ephemeral hosts (`a27e444`).
- **Device pairing + heartbeat + "Connect your computer" panel** (`6fd124b`,
  `76ab1c5`) — the browser-based way to link a computer with a short code.
- **The local agent**: persistent profile + one-time login (`1c0c760`), one
  persistent browser context to avoid "browser has been closed" (`d4ef29a`),
  reconnect with just `python -m agent.agent` (`27b53d1`).
- **Packaging into a downloadable macOS app** (`8d38dd7`) and the realization that
  **Chromium can't be bundled** (it breaks code-signing) so it downloads on first run
  (`b6e7385`), later verified with a `--check` mode (`a133748`).

Supporting fixes in this era: create the SQLite dir on boot (`c0619a1`), never hang
keyword extraction on failure + show the user why (`37b1581`, `93dfc7d`), lock résumé
edits while a job runs (`86d9dff`), preserve the résumé file extension on download so
Unstop's PDF step doesn't choke on a mis-read `.docx` (`de737ec`).

---

## Part 3 — Problem → Cause → Solution log

Each entry is a real issue we hit, why it happened, and what fixed it.

### 3.1 Frontend searches also returned full-stack roles
- **Symptom:** searching "frontend" surfaced "full stack" internships too.
- **Cause:** Internshala's keyword search matches the JD, not just the title, and
  there was **no post-scrape relevance filter** — whatever the site returned got
  listed. The keywords genuinely overlap.
- **Decision:** left as-is by choice — the listings are legitimate keyword matches and
  the user decides per listing whether to apply. (A title include/exclude filter was
  offered but declined.)

### 3.2 Every listing showed "Internshala is rate-limiting"
- **Symptom:** all search results came back flagged "Internshala is rate-limiting."
- **Cause:** during **search**, the agent clicked **"Apply now" on every listing** just
  to detect custom questions. A burst of Apply clicks is exactly what trips
  Internshala's throttle. (Earlier we'd at least separated this from an incomplete
  profile — `bd59443`.)
- **Solution:** **stop clicking Apply during search.** Search now only *reads* each
  listing page for full details; question detection moved to **apply time**, on demand,
  one listing at a time (`2480d5c`). This was the single biggest fix.

### 3.3 Reworking search + apply around the fix
- Added **rich detail scraping** without an apply click (`get_listing_info`,
  `fetch_details`).
- **Apply flow** now: click Apply → if no questions, submit; if custom questions,
  return them so the user can answer (AI-drafted, editable) before submitting
  (`2480d5c`). New `/api/answers` endpoint drafts answers from résumé + JD.

### 3.4 UI: card interactions and the missing illustrations
- **Asks:** drop the extra "View details" button (click the card instead), show a
  single **Apply** button (not "Open on Internshala"), and illustrations weren't
  showing (`36fa33d`).
- **Illustrations, attempt 1:** `.dockerignore` was excluding
  `assets/illustration/*.png`, so they existed locally but never got into the deployed
  image. Removed the exclusion + compressed the images from ~2.4 MB to ~0.3 MB each.
- **Illustrations, real fix:** they *still* 404'd — the deployed server returned 404
  for **everything under `/assets`**, while `/static` (where JS/CSS load) worked fine.
  Moved the images to `frontend/static/illustration/` and referenced `/static/…`
  (`a48c229`). The user's clue — "they show in demo but not live" — plus a direct URL
  test returning `{"detail":"Not Found"}` nailed it.

### 3.5 Bulk auto-apply, made throttle-safe
- **Concern:** applying to many listings could re-trip the throttle, and question
  listings shouldn't be blindly submitted.
- **Solution:** bulk = **skip & flag** (auto-submit only no-question listings; flag the
  rest for manual answering), applies paced ~4s apart, and **single-pass apply** so
  each Internshala application is **one** form load instead of check-then-submit
  (`bcbfe71`). Also tinted the detail modal with the card's colour.

### 3.6 Controlling the agent from the web app
- **Ask:** why can't we stop/restart the agent from the dashboard?
- **Reality:** the server has **no inbound channel** to the user's machine (the agent
  polls out), so it can't kill/start a process — only leave notes the agent reads.
- **Solution:** cooperative **Pause/Resume** (claim returns nothing while paused) and
  **Stop** (cancel queued jobs + a `stop_seq` the running search checks between
  listings; bulk stops in the browser loop) (`ecf96d9`). A true "restart to load new
  code" needs an auto-updater — deferred.

### 3.7 Unstop: repetitive per-application fields + custom questions
- **Symptom:** Unstop auto-apply failed asking for **location**, **course duration**,
  and **two agreement checkboxes** every time; and a custom question was reported as
  `missing: text` instead of being flagged.
- **Cause:** those fields came only from empty env vars, `_accept_terms` ticked just
  **one** box, and question detection only looked at `<textarea>` (missing a required
  `text` field).
- **Solution:** a per-user **apply profile** (city + course duration) set in the web
  app and injected into apply jobs; tick **all** required agreement boxes;
  course-duration matched by value or label (`9138444`). Then Unstop custom questions
  became `needs_answers` (detected across textareas / contenteditable / required
  inputs) with the answers filled on a second pass, and Unstop **details scraped** from
  its search API (`1dbfd41`).

### 3.8 Making onboarding actually usable (packaging + wizard)
- **macOS app:** building and *running* it exposed two crashes — the packaged app was
  missing `python-dotenv` (made the `.env` load optional) and `rich` (added it); and
  `--check` now imports the full apply path so such gaps fail the build, not the user
  (`95b01ee`). Also auto-opens platform logins after pairing and zips for release
  (`9cd003f`).
- **Per-OS commands:** the Connect modal only showed **bash**, which fails on Windows —
  added PowerShell/cmd variants and OS detection (`989cf0d`).
- **Windows agent:** a **console app** built on CI (no Windows machine needed) via
  `.github/workflows/build-windows.yml`, plus an **interactive pairing** fallback so a
  packaged app can prompt for the code (`6a54834`).
- **Guided wizard:** replaced the wall-of-text modal with **pick your computer →
  numbered steps → live "Connected ✓"** (`f4221a6`).
- **Correct commands:** the setup command had a placeholder repo URL and the wrong
  folder name; fixed to the real repo and `cd internhelper`, split into lines that work
  in PowerShell too (`ed4d71f`).

### 3.9 "There is no `requirements-agent.txt`"
- **Symptom:** following the clone command, the file didn't exist.
- **Cause:** all this work lived on `path-b-multitenant`; the **default branch `main`
  had none of it** (no `agent/`, no `requirements-agent.txt`), and `git clone` fetches
  the default branch.
- **Solution:** fast-forwarded **`main` to the branch** (clean, 37 commits, no
  conflicts) and now keep both in sync. This also enabled the Actions "Run workflow"
  button (workflows must be on the default branch).

### 3.10 Windows: agent connects but never asks to log in / "waiting for agent"
- **Symptom:** the agent paired (dashboard showed connected) but no login prompt
  appeared and searches sat on "waiting for agent."
- **Cause:** the login prompt was only in the **console window** (hidden behind the
  browser), and the job loop only started **after** the blocking login step — so if
  login stalled, jobs never ran.
- **Solution:** an on-page **InternHelper banner** on each login page so the browser
  itself guides you, clearer console messaging, and surfaced browser-setup errors
  (`aa95301`).

### 3.11 Windows: only the Unstop login worked; Internshala showed nothing
- **Symptom:** the browser opened, Unstop login worked, Internshala login was blank —
  but typing Internshala manually worked.
- **Cause:** the previous fix started the **job loop during login**, and the agent
  **reuses a single browser tab** — a running search kept navigating that tab away from
  the Internshala login (Unstop was just the last page loaded).
- **Solution:** go back to **login-first** — log into both platforms, *then* start the
  loop, so nothing fights for the tab (`53cdc4d`). (The `/login/user` URL was verified
  correct — HTTP 200 — so it wasn't the URL.)

### 3.12 Windows: couldn't fill Unstop location & other fields
- **Symptom:** Unstop apply still failed on location on Windows.
- **Cause:** on Mac a leftover `.env` `USER_LOCATION` filled it; a fresh Windows clone
  has no `.env`, so the **only** source is the apply profile — and Unstop's location
  box needs a **selected autocomplete suggestion**, not just typed text.
- **Solution:** harden the autofill — broader suggestion selectors + a **keyboard
  fallback** (ArrowDown+Enter) to select the first result — and **log** the profile the
  agent received and the location it set, so it's visible whether the city came through
  (`e38b2bf`).

### 3.13 Hangs and vague failures
- **Ask:** put a time limit on operations and show a real reason (e.g. eligibility) on
  failure.
- **Solution:** hard **timeouts** per operation (search 480s, apply 180s, sync 180s →
  clear messages) and **`ineligibility_reason()`** that detects "not eligible /
  applications closed / deadline passed / already applied / registrations closed" and
  surfaces it as the failure message (`6287516`).

### 3.14 Documentation
- `ARCHITECTURE.md` — the full "how it works today" map (`4062384`).
- This file — the journey.

---

## Part 4 — Lessons that keep paying off

- **Don't automate what looks like a human burst.** The rate-limit fix wasn't a
  clever bypass — it was *not clicking Apply* until the user actually applies.
- **A single reused browser tab** is great for a quiet UX but means login and jobs
  can't run at the same time — order matters (login first).
- **The server can't reach the user's machine.** Every "control the agent" feature is
  cooperative, over the poll channel.
- **`/static` works on the deploy; `/assets` didn't.** Serve user-facing files from a
  mount you've proven loads.
- **New settings → new tables**, because `create_all` won't alter existing ones.
- **Build *and run* the packaged app in CI/`--check`.** Import-time gaps (`dotenv`,
  `rich`) never reach a user that way.
- **`git clone` gets the default branch.** Ship the code onto `main`, not just a
  feature branch.
- **When stuck, ask the user for one concrete signal.** "It shows in demo but not
  live" and a direct-URL test cracked the illustrations in one step.

---

## Part 5 — What's still open

- **Auto-update** for the agent (so fixes don't need a manual restart/rebuild).
- **Code-signing** (Apple Developer ID; Windows OV/EV) to drop the OS warnings.
- **Publishing the packaged apps** + setting `AGENT_DOWNLOAD_MAC` /
  `AGENT_DOWNLOAD_WINDOWS` so the wizard shows one-click downloads.
- Optional: a cleaner "Not eligible" card state (no misleading "tap to retry"),
  a one-click `internhelper://` pairing deep link, more platforms via new adapters.
