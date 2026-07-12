# InternHelper — Project Journal

A full account of what was built, why each decision was made, what broke,
and what comes next. Written so any future session can pick up with full context.

---

## What it is

An AI-powered Internshala auto-apply tool. You upload your resume(s), it scrapes
matching internship listings, generates tailored answers to every application
question using an LLM, and lets you approve/edit each answer before anything is
submitted. Human in the loop the whole way — no blind submissions.

Two interfaces exist: a command-line pipeline (`main.py`) and a web UI
(`server.py` + `frontend/`). Both drive the same underlying Python modules.

---

## Repo layout

```
internshala-autoapply/
├── config.py                  # all env vars loaded once here
├── main.py                    # CLI entry point
├── server.py                  # FastAPI web server
│
├── llm/                       # pluggable LLM layer
│   ├── base.py                # BaseLLM abstract class
│   ├── __init__.py            # get_llm() factory
│   ├── anthropic_llm.py       # claude-opus-4-8
│   ├── openai_llm.py          # gpt-4o
│   ├── groq_llm.py            # llama-3.3-70b-versatile (free tier)
│   └── local_llm.py           # HuggingFace / Ollama / custom stub
│
├── auth/
│   └── session.py             # Playwright login + session persistence
│
├── scraper/
│   └── internshala.py         # search listings, scrape JD + questions
│
├── applicant/
│   ├── resume_parser.py       # pdf / docx / image / txt
│   ├── answer_generator.py    # LLM answer per question
│   └── keyword_extractor.py   # LLM keywords from resume (used by web server)
│
├── apply/
│   └── form_filler.py         # Playwright form fill + submit
│
├── review/
│   └── cli_review.py          # terminal approve / edit / skip loop
│
├── frontend/
│   ├── index.html             # three-step wizard
│   └── static/
│       ├── style.css          # dark theme
│       └── app.js             # all UI logic (no framework)
│
└── data/
    ├── resumes/               # uploaded resume files (gitignored)
    └── sessions/              # saved Playwright storage state (gitignored)
```

---

## How to run

### Prerequisites

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Environment

Copy `.env.example` to `.env` and fill in your values:

```env
INTERNSHALA_EMAIL=your@email.com
INTERNSHALA_PASSWORD=yourpassword

LLM_PROVIDER=groq          # anthropic | openai | groq | local

ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...

LOCAL_MODEL_PATH=./models/my_model
LOCAL_MODEL_TYPE=huggingface   # huggingface | ollama | custom

RESUME_PATH=./data/resume.txt  # only needed for CLI mode
```

Only the API key that matches `LLM_PROVIDER` is used at runtime.

### CLI mode

```bash
python main.py \
  --keywords "python machine learning" \
  --location "work from home" \
  --max 10
```

Flags: `--keywords / -k`, `--location / -l`, `--stipend-min / -s`,
`--max / -m`, `--reset-session` (force re-login).

### Web UI mode

```bash
uvicorn server:app --reload --port 8000
# open http://localhost:8000
```

Three steps in the browser:
1. Upload one resume per role (frontend / backend / fullstack / etc.)
2. Set search location, minimum stipend, max listings per role
3. Review results — generate answers, edit them, submit or skip

---

## Module-by-module notes

### config.py

Single `load_dotenv()` call at import time. Every other module imports
constants from here — no `os.getenv` scattered around. When adding a new
env var, add it here first and to `.env.example`.

### llm/

`BaseLLM` defines one method: `generate(system_prompt, user_prompt) -> str`.
`get_llm()` reads `LLM_PROVIDER` from config and returns the right backend.

**Active provider: Groq** (`LLM_PROVIDER=groq`). Groq's free tier gives enough
calls for development with `llama-3.3-70b-versatile`. Anthropic is also wired
up but the account ran out of credits during development.

**Local model stub** (`local_llm.py`): not yet trained. Set `LOCAL_MODEL_TYPE`
to `huggingface`, `ollama`, or `custom`. The `custom` path raises
`NotImplementedError` by design — override `_load_model` and `generate`.

### auth/session.py

Internshala's login page has a CAPTCHA that automation cannot solve.
Strategy:
1. Fill `#email` and `#password` programmatically.
2. Print a message asking the user to solve the CAPTCHA manually.
3. `page.wait_for_url("**/student/dashboard**", timeout=120_000)` — wait up
   to 2 minutes for the user to click Login.
4. Save `context.storage_state()` to `data/sessions/internshala_session.json`.
5. On every subsequent run, load the saved state and validate it by navigating
   to the dashboard. If the session is still live, skip login entirely.

The browser runs headed (`headless=False`) so the user can interact with it.

### scraper/internshala.py

**`search_internships(context, filters)`**
Builds a search URL and reads `.individual_internship` cards. Selectors that
worked as of mid-2025: `.job-title-href` for the title link, `.company-name`
for the company, `.stipend` for the stipend. Returns a list of dicts with
`title`, `company`, `url`, `stipend`.

**`get_listing_details(context, url)`**
Loads the listing detail page, reads `.internship_details` for the JD, then
clicks the Apply button and waits 3 seconds for the questions AJAX modal to
load. Reads questions from `#questions .modal-body`. Returns
`{"jd": ..., "questions": [...], "profile_incomplete": True/False}`.

**`_build_search_url(filters)`**
Constructs Internshala's URL format:
`/internships/keywords-{kw},work-from-home-internships/`

### applicant/resume_parser.py

`load_resume(path)` dispatches by extension:
- `.pdf` → `pdfplumber`
- `.docx` → `python-docx`
- `.png / .jpg / .jpeg / .webp` → Claude Haiku vision API (base64 image, no
  Tesseract required)
- anything else → plain `open(...).read()`

Image parsing uses `claude-haiku-4-5-20251001` directly (not `get_llm()`)
because it needs vision capability regardless of which text LLM is configured.

### applicant/keyword_extractor.py

Used by the web server's multi-resume search, not by the CLI (the CLI takes
`--keywords` as a flag). Asks the active LLM to return 3-6 comma-separated
Internshala search terms given the resume text and the role label. If LLM
extraction fails, the server falls back to using the role name itself as the
keyword.

### applicant/answer_generator.py

Calls `get_llm().generate()` once per question. The system prompt:
- Frames the LLM as helping a student, not a corporate professional
- Caps answers at 150 words by default
- **Explicitly forbids fabricating skills not in the resume**

### review/cli_review.py

`review_application(listing, answers) -> (should_submit, final_answers)`

Uses `questionary` for rich terminal prompts. For each question, the user
chooses Keep / Edit / Skip. A final confirm prompt before any submission.

### apply/form_filler.py

`submit_application(context, listing, answers) -> bool`

Re-navigates to the listing, clicks Apply, then either:
- Fills textareas by matching label text to question text (for question-based
  applications)
- Clicks the modal's submit button directly (for zero-question applications)

Detects the profile-incomplete redirect after clicking Apply and returns False
immediately rather than hanging.

### server.py

FastAPI with in-memory stores (no database):

```python
_resumes: dict[str, dict]   # role → {path, text, keywords, keyword_status}
_jobs:    dict[str, dict]   # job_id → {status, listings, error}
```

All Playwright work runs in `BackgroundTasks` (off the async event loop).
The frontend polls `/api/job/{id}` every 1.5 s until `status == "ready"`.

Key endpoints:
| Method | Path | What it does |
|--------|------|--------------|
| POST | `/api/resumes` | Upload resume, trigger keyword extraction |
| GET | `/api/resumes` | List all resumes + status |
| DELETE | `/api/resumes/{role}` | Remove resume |
| PATCH | `/api/resumes/{role}/keywords` | Save edited keyword chips |
| POST | `/api/resumes/{role}/retry-extract` | Re-run failed keyword extraction |
| POST | `/api/search/multi` | Start parallel search across all resumes |
| GET | `/api/job/{job_id}` | Poll job status + listings |
| POST | `/api/generate/{job_id}/{index}` | Generate answers for one listing |
| POST | `/api/submit` | Approve (submit) or skip one listing |

### frontend/

Pure HTML + CSS + JavaScript. No build step, no framework, no bundler.

`app.js` state: `currentJobId`, `pollTimer`, `activeFilter` (role pill).

Flow:
1. Upload → `POST /api/resumes` → `pollResumes()` every 1.5 s until all
   `keyword_status` values leave `"extracting"`.
2. Search → `POST /api/search/multi` → `pollJob()` every 2 s until
   `job.status === "ready"` → `renderListings()`.
3. Per listing:
   - `qCount > 0` → Generate button → polls until status `"ready"` →
     Review & Submit button → modal with editable textareas → approve/skip.
   - `qCount === 0 && !profile_incomplete` → Apply directly button →
     skips generation, submits immediately.
   - `profile_incomplete` → "Complete profile ↗" link to Internshala.

---

## The development journey (what broke and how it was fixed)

These match the three `fix:` commits in the git log.

### Bug 1 — WFH search returned 0 listings

**What happened:** The first search run returned an empty listing set.

**Root cause:** Internshala's work-from-home URL is
`/internships/work-from-home-internships/` but the URL builder was appending
`work-from-home` (without `-internships`), which matched no page.

**Fix:** Change the slug in `_build_search_url`.

**Commit:** `fix: scraper — wrong URL segment caused WFH search to return 0 results`

### Bug 2 — All listings showed 0 questions

**What happened:** Every listing came back with an empty `questions` list even
though the Internshala detail page clearly had application questions.

**Root cause:** Application questions are not in the initial page HTML. They are
loaded via an XHR request that fires only after the user clicks the Apply button,
then injected into a modal (`#questions .modal-body`). Reading the page source
directly always returned nothing.

**Fix:** In `get_listing_details`, click the Apply button and wait 3 seconds
before trying to read the modal DOM.

**Commit:** `fix: scraper — click Apply button to load questions from AJAX modal`

### Bug 3 — Scraper hung on some listings; form filler submitted to wrong place

**What happened:** On listings where the student's Internshala profile was
incomplete, clicking Apply redirected the browser to `/student/resume` instead
of opening the questions modal. The scraper then waited forever for a modal that
never appeared. The form filler silently tried to fill a resume-edit page.

**Root cause:** Internshala gates the Apply modal behind a complete profile.

**Fix:** After clicking Apply, check `page.url` for `resume` or `profile`.
Scraper returns `{"profile_incomplete": True}` and exits immediately. Form filler
returns `False`. The UI surfaces a "Complete profile ↗" link.

**Commit:** `fix: detect and surface profile-incomplete redirect in scraper and form filler`

### Discovery — Keyword extraction failed for all resumes

**What happened:** After adding the keyword extractor, every resume showed
"Extracting keywords…" and then flipped to an error: "credit balance is too low".

**Root cause:** The Anthropic account had zero credits (free tier exhausted).

**Fix:** Added Groq as a provider (`LLM_PROVIDER=groq`). Groq's free tier
provides `llama-3.3-70b-versatile` with no billing setup. The `.env` was updated
to `LLM_PROVIDER=groq`. The `_friendlyError` function in `app.js` maps the
raw API error to a readable message and surfaces a Retry button.

**Commit:** `feat: llm — add Groq backend (llama-3.3-70b) as free-tier alternative`

---

## Known limitations and next steps

### Must do before this is reliably usable

1. **Complete your Internshala profile.** If the profile is incomplete, no
   application questions will load and the tool can only do zero-question
   (one-click) applies. Go to internshala.com/student/resume and fill everything.

2. **Revoke compromised API keys.** Both the Anthropic key and the Groq key
   were shared in conversation during development. Revoke them and generate
   new ones:
   - Anthropic: console.anthropic.com → API Keys
   - Groq: console.groq.com → API Keys
   Then update `.env` with the new keys.

### Planned improvements

- **Stipend filter:** The `stipend_min` filter is passed through to the
  backend but Internshala's URL does not support a stipend filter parameter.
  Currently collected but not applied. Need to post-filter in `search_internships`
  by parsing the stipend string from each card.

- **Multi-resume parallel search:** The current server implementation runs
  searches sequentially role by role inside one Playwright context. True
  parallelism would require multiple browser contexts or async scraping.

- **Resume persistence across server restarts:** `_resumes` is in-memory.
  Restarting the server loses all uploaded resumes. A simple JSON file store
  in `data/` would fix this without needing a database.

- **Local/self-trained model:** `llm/local_llm.py` is a stub. The
  `custom` backend raises `NotImplementedError`. To wire in your own model,
  subclass `BaseLLM` and implement `generate`, or override `_load_model` and
  `generate` directly in `LocalLLM`.

- **Auto-login:** The CAPTCHA pause is manual by design. If Internshala ever
  offers a proper OAuth or API, login could be automated. Until then the
  saved-session approach (solve once, reuse indefinitely) is the right trade-off.

- **Error recovery in the web UI:** If Playwright crashes mid-search, the job
  is stuck at `status: "searching"` with no recovery. A timeout on the job
  poll + a retry button would fix this.

- **Answer quality:** The current prompt caps answers at 150 words. For some
  questions (cover letter, "tell us about yourself") a longer limit is better.
  The `max_tokens` in the LLM backends and the word-cap instruction in the
  system prompt are the two dials to turn.

---

## Commit conventions

This repo follows [Conventional Commits](https://www.conventionalcommits.org).
Every commit subject starts with a **type**, optionally followed by a scope and
an em-dash description:

```
<type>: <scope> — <short, imperative description>
```

Examples from the history:
`feat: scraper — search Internshala listings with keyword/location URL builder`,
`fix: correct internshala search url to avoid redirect loop`.

### Commit types used

| Type | When to use it |
|------|----------------|
| `feat` | A new feature or capability (new module, endpoint, backend, UI step). |
| `fix` | A bug fix — corrects broken or wrong behavior. |
| `docs` | Documentation only (this file, comments, README). |
| `chore` | Scaffolding, config, dependencies, tooling — no app-behavior change. |

Additional standard types available if needed: `refactor` (restructure without
behavior change), `test` (add/adjust tests), `style` (formatting only),
`perf` (performance), `build` / `ci` (build system or pipeline).

The `scope` (e.g. `scraper`, `llm`, `applicant`) is optional but preferred — it
names the module the change touches and matches the `Repo layout` above. Keep
the description in the imperative mood ("add", "fix", "correct"), lowercase, and
under ~72 characters. Put the *why* and details in the commit body.

---

## Security notes

- `.env` is gitignored. Never commit it.
- `data/sessions/` is gitignored. The session JSON contains auth cookies —
  treat it like a password.
- `data/resumes/` is gitignored. Resume files contain PII.
- The `.gitignore` uses glob negation (`data/sessions/*` + `!data/sessions/.gitkeep`)
  to track the directory structure without tracking the files inside.
- The LLM sends resume text to a third-party API. If the resume is sensitive,
  use `LLM_PROVIDER=local` once a local model is wired up.

---

## LLM provider quick reference

| Provider | Key env var | Model | Cost |
|----------|-------------|-------|------|
| `anthropic` | `ANTHROPIC_API_KEY` | claude-opus-4-8 | Paid |
| `openai` | `OPENAI_API_KEY` | gpt-4o | Paid |
| `groq` | `GROQ_API_KEY` | llama-3.3-70b-versatile | Free tier |
| `local` | — | whatever LOCAL_MODEL_PATH points to | Free |

Switch provider by changing `LLM_PROVIDER` in `.env`. No code changes needed.
