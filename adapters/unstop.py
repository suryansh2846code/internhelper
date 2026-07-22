"""Unstop adapter.

Search runs against Unstop's public JSON API (no login). Auto-apply drives the
multi-step registration wizard at /competitions/{id}/register — Step 1 is
pre-filled from the user's Unstop profile, so the flow is: upload résumé →
click Next through the steps → final submit. Listings with open-ended questions
(a visible textarea) are handed back for manual apply.

Auto-apply is gated behind `supports_auto_apply` until validated on a real
listing (there is no dry-run — the final step submits a real application)."""
import os
import re
from urllib.parse import quote

from playwright.sync_api import BrowserContext

import config
from adapters.base import PlatformAdapter
from applicant.resume_pdf import ensure_pdf

SEARCH_API = "https://unstop.com/api/public/opportunity/search-result"
REGISTER_URL = "https://unstop.com/competitions/{id}/register"
MAX_STEPS = 8

# The step's main call-to-action (advance or submit) — anything but "Back".
PRIMARY_CTA = (r"^\s*(next|save & next|continue|update details|submit|register"
               r"|apply now|apply|confirm.*|proceed|done|finish)\s*$")

SUCCESS_MARKERS = (
    "registered successfully", "successfully registered", "registration successful",
    "you have registered", "you are registered", "you're registered",
    "already registered", "application submitted",
)


class UnstopAdapter(PlatformAdapter):
    name = "unstop"
    label = "Unstop"
    supports_auto_apply = True
    login_url = "https://unstop.com/login"

    def search(self, context: BrowserContext, filters: dict) -> list[dict]:
        # Load Unstop once so the request context picks up its cookies/CSRF.
        page = context.new_page()
        try:
            page.goto("https://unstop.com/internships", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1200)
        except Exception:
            pass

        keywords = (filters.get("keywords") or "").strip()
        per_page = int(filters.get("max_listings", 10))
        url = (f"{SEARCH_API}?opportunity=internships&page=1&per_page={per_page}"
               f"&oppstatus=open&searchTerm={quote(keywords)}")

        listings: list[dict] = []
        try:
            resp = context.request.get(url)
            if resp.ok:
                items = ((resp.json() or {}).get("data") or {}).get("data") or []
                for it in items:
                    org = it.get("organisation") or {}
                    listings.append({
                        "id": it.get("id"),
                        "title": (it.get("title") or "").strip(),
                        "company": org.get("name", "Unknown"),
                        "url": it.get("seo_url") or f"https://unstop.com/{it.get('public_url', '')}",
                        "stipend": _stipend(it.get("jobDetail") or {}),
                        "logo": org.get("logoUrl") or it.get("logoUrl2") or "",
                        # Full details ride along from the search API — no extra request.
                        "jd": _html_to_text(it.get("details")),
                        "skills": _skills_from(it),
                        "meta": _meta_from(it),
                    })
        except Exception as e:
            print(f"[unstop] search error: {e}")
        return listings

    def classify(self, context: BrowserContext, url: str) -> dict:
        # Candidate details are pre-filled from the profile; question-detection
        # is deferred to apply(), which bails if it hits an open-ended question.
        return {"jd": "", "questions": [], "profile_incomplete": False}

    def sync_applications(self, context: BrowserContext) -> list[dict]:
        # Unstop exposes registered opportunities via an authed JSON API.
        page = context.new_page()
        try:
            page.goto("https://unstop.com/user/registrations", wait_until="domcontentloaded", timeout=40_000)
            page.wait_for_timeout(3500)
            token = next((c["value"] for c in context.cookies()
                          if c["name"] == "access_token" and "unstop" in c.get("domain", "")), None)
            if not token:
                print("[unstop] no access token — can't sync")
                return []

            out: list[dict] = []
            for page_no in range(1, 7):
                api = ("https://unstop.com/api/user/registered-opportunities"
                       f"?page={page_no}&per_page=30&filterName=type,status&filterValue=all,all")
                r = context.request.get(api, headers={"Authorization": f"Bearer {token}"})
                if not r.ok:
                    break
                items = ((r.json() or {}).get("data") or {}).get("data") or []
                for it in items:
                    url = it.get("seo_url") or f"https://unstop.com/{it.get('public_url', '')}"
                    if "/internships/" not in url:  # skip hackathons/competitions/quizzes
                        continue
                    out.append({
                        "url": url,
                        "title": (it.get("title") or "").strip(),
                        "company": "",
                        "status": _reg_status(it),
                    })
                if len(items) < 30:
                    break
            return out
        except Exception as e:
            print(f"[unstop] sync error: {e}")
            return []
        finally:
            page.close()

    def apply(self, context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
        r = self._run(context, listing, answers or {})
        return r["ok"], r["message"]

    def try_apply(self, context: BrowserContext, listing: dict, answers: dict) -> dict:
        # Same wizard, richer result: surfaces custom questions as needs_answers.
        return self._run(context, listing, answers or {})

    def _run(self, context: BrowserContext, listing: dict, answers: dict) -> dict:
        opp_id = listing.get("id") or _id_from_url(listing.get("url", ""))
        if not opp_id:
            return {"ok": False, "message": "Couldn't determine the Unstop opportunity id."}

        page = context.new_page()
        try:
            page.goto(REGISTER_URL.format(id=opp_id), wait_until="domcontentloaded", timeout=40_000)
            page.wait_for_timeout(4000)

            if "/login" in page.url.lower():
                return {"ok": False, "not_logged_in": True,
                        "message": "Not logged into Unstop — reconnect and retry."}

            from apply.form_filler import ineligibility_reason
            elig = ineligibility_reason(page)
            if elig:
                return {"ok": False, "message": elig}

            # Unstop only accepts PDF résumés — convert if needed.
            resume = ensure_pdf(listing.get("resume_path"))

            # Fill the per-application fields Unstop doesn't pull from the profile.
            page.wait_for_timeout(1500)
            _fill_candidate_details(page, listing)

            for _ in range(MAX_STEPS):
                page.wait_for_timeout(1200)

                if _is_success(page):
                    return {"ok": True, "message": "Registered on Unstop."}

                # Custom (open-ended) questions on this step. First pass with no
                # answers -> hand them back to the user; else fill and continue.
                questions = _open_questions(page)
                if questions:
                    if not answers:
                        return {"ok": False, "needs_answers": True,
                                "questions": [q["label"] for q in questions], "jd": listing.get("jd", ""),
                                "message": f"{len(questions)} custom question(s) to answer"}
                    _fill_custom_answers(page, answers)

                _upload_resume(page, resume)

                # Click the step's main CTA (Next / Update Details / Submit / …),
                # not "Back". This unifies advancing and final submit.
                cta = _find_button(page, PRIMARY_CTA)
                if not cta:
                    return {"ok": False, "message": "Couldn't find a submit/next button on the Unstop form."}

                before = _step_signature(page)
                try:
                    cta.click(timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(3000)

                if _is_success(page):
                    return {"ok": True, "message": "Registered on Unstop."}
                if _step_signature(page) == before:
                    # Didn't advance — a required field is still blocking.
                    missing = _missing_required(page)
                    hint = f" (missing: {', '.join(missing)})" if missing else ""
                    return {"ok": False, "message": f"Complete your Unstop profile to auto-apply{hint}."}
                # advanced to the next step -> loop

            return {"ok": False, "message": "Unstop form had too many steps — apply manually."}
        except Exception as e:
            return {"ok": False, "message": f"Error applying on Unstop: {e}"}
        finally:
            page.close()


# ── helpers ────────────────────────────────────────────────────────────────────

def _reg_status(item: dict) -> str:
    """Map an Unstop registered-opportunity to our status set (best effort)."""
    if item.get("userRejectedRoundStatus"):
        return "rejected"
    s = (item.get("status") or "").lower()
    if any(k in s for k in ("select", "winner", "offer", "hired")):
        return "offer"
    if any(k in s for k in ("shortlist", "interview")):
        return "interview"
    if "review" in s:
        return "under review"
    return "applied"


def _html_to_text(html: str | None) -> str:
    """Flatten Unstop's HTML `details` field to readable plain text."""
    if not html:
        return ""
    import html as _htmllib
    s = re.sub(r"<\s*br\s*/?>", "\n", html, flags=re.I)
    s = re.sub(r"</\s*(p|div|li|h[1-6])\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*li[^>]*>", "• ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _htmllib.unescape(s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _skills_from(item: dict) -> list[str]:
    out = []
    for s in (item.get("required_skills") or []):
        name = (s.get("skill_name") or s.get("skill") or "").strip()
        if name and name not in out:
            out.append(name)
    return out[:12]


def _meta_from(item: dict) -> dict:
    meta: dict[str, str] = {}
    locs = item.get("locations") or []
    if locs:
        city = ", ".join(filter(None, [locs[0].get("city"), locs[0].get("state")]))
        if city:
            meta["Location"] = city
    elif item.get("region"):
        meta["Location"] = str(item["region"]).title()
    meta["Type"] = "Paid" if item.get("isPaid") else "Unpaid"
    end = item.get("end_date") or ""
    if end:
        meta["Apply By"] = end[:10]
    return meta


def _stipend(job_detail: dict) -> str:
    if not job_detail.get("show_salary"):
        return "Not disclosed"

    def _amt(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    lo, hi = _amt(job_detail.get("min_salary")), _amt(job_detail.get("max_salary"))
    if lo and hi:
        return f"₹{lo:,} - ₹{hi:,}/month"
    if lo or hi:
        return f"₹{(lo or hi):,}/month"
    return "Unpaid"


def _id_from_url(url: str) -> str | None:
    m = re.search(r"-(\d+)/?$", url)
    return m.group(1) if m else None


def _find_button(page, pattern: str):
    loc = page.get_by_role("button", name=re.compile(pattern, re.I))
    for i in range(loc.count()):
        if loc.nth(i).is_visible():
            return loc.nth(i)
    return None


def _fill_candidate_details(page, listing: dict) -> None:
    """Fill Unstop's per-application fields: location, course duration, skills,
    and the required agreement checkboxes.

    Location and course duration come from the user's apply profile (set in the
    web app and injected into the apply job), falling back to the local env vars
    for the standalone/CLI flow."""
    location = (listing.get("apply_location") or config.USER_LOCATION or "").strip()
    duration = (listing.get("apply_course_duration") or config.USER_COURSE_DURATION or "").strip()

    # Location — type the city and pick the matching autocomplete suggestion.
    if location:
        try:
            loc = page.wait_for_selector("input[name='player_location']", timeout=8000)
        except Exception:
            loc = None
        if loc and not (loc.input_value() or "").strip():
            for _ in range(2):  # retry — the suggestion must be clicked to register
                try:
                    loc.click()
                    loc.fill("")
                    loc.type(location, delay=90)
                    page.wait_for_timeout(2600)
                    _click_suggestion(page, location)
                    page.wait_for_timeout(800)
                    if (loc.input_value() or "").strip():
                        break
                except Exception:
                    pass

    # Course duration — select the profile value (by radio value or label text),
    # else leave Unstop's default / pick the first option.
    _select_course_duration(page, duration)

    # Skills — add each from the matched résumé's keywords.
    _fill_skills(page, listing.get("skills") or [])

    # Tick the required agreement checkboxes (Terms, declaration, …).
    _accept_terms(page)


def _select_course_duration(page, duration: str) -> None:
    try:
        radios = page.query_selector_all("input[name='course_duration']")
        if not radios or any(r.is_checked() for r in radios):
            return
        chosen = None
        if duration:
            for r in radios:  # exact radio value, e.g. "4"
                if (r.get_attribute("value") or "") == duration:
                    chosen = r
                    break
            if not chosen:      # else a radio whose label mentions the duration
                for r in radios:
                    rid = r.get_attribute("id")
                    lbl = page.query_selector(f"label[for='{rid}']") if rid else None
                    txt = (lbl.inner_text() if lbl else "") or ""
                    if duration.lower() in txt.lower():
                        chosen = r
                        break
        _click_input(page, chosen or radios[0])
    except Exception:
        pass


def _click_input(page, el) -> None:
    """Select a radio/checkbox, falling back to clicking its label."""
    try:
        el.check(timeout=1500)
        return
    except Exception:
        pass
    try:
        page.evaluate(
            "(e) => { const id = e.id;"
            " const lbl = (id && document.querySelector(`label[for='${id}']`)) || e.closest('label') || e.parentElement;"
            " if (lbl) lbl.click(); }",
            el,
        )
    except Exception:
        pass


def _accept_terms(page) -> None:
    """Tick every required agreement checkbox (Unstop's register step has more
    than one — e.g. Terms & Conditions and a declaration).

    The real inputs are visually hidden by custom styling and sit below the fold,
    so we click each one's label[for] after scrolling. We tick all unchecked
    boxes except newsletter/marketing opt-ins."""
    SKIP = ("newsletter", "promotion", "marketing", "update me", "updates",
            "offers", "subscribe", "notif")
    for cb in page.query_selector_all("input[type=checkbox]"):
        try:
            if page.evaluate("(e) => e.checked", cb):
                continue
            ctx = (page.evaluate("(e) => (e.closest('label') || e.parentElement || {}).innerText || ''", cb) or "").lower()
            if any(k in ctx for k in SKIP):
                continue
            cid = cb.get_attribute("id")
            label = page.query_selector(f"label[for='{cid}']") if cid else None
            if label:
                label.scroll_into_view_if_needed()
                label.click()
            else:
                page.evaluate("(e) => { const l = e.closest('label') || e.parentElement; if (l) l.click(); }", cb)
            page.wait_for_timeout(350)
        except Exception:
            continue


def _click_suggestion(page, term: str) -> bool:
    term = term.lower()
    for sel in ("[role=option]", "mat-option", ".autocomplete-item",
                "[class*=suggestion]", "[class*=dropdown] li"):
        for opt in page.query_selector_all(sel):
            try:
                if opt.is_visible() and term.split(",")[0] in (opt.inner_text() or "").lower():
                    opt.click()
                    page.wait_for_timeout(500)
                    return True
            except Exception:
                continue
    return False


def _fill_skills(page, skills: list[str]) -> None:
    inp = page.query_selector("input[placeholder*='skill' i]")
    if not inp or not skills:
        return
    for skill in skills[:6]:
        try:
            inp.click()
            inp.fill("")
            inp.type(skill, delay=60)
            page.wait_for_timeout(1500)
            if not _click_suggestion(page, skill):
                inp.press("Enter")
            page.wait_for_timeout(500)
        except Exception:
            continue


def _step_signature(page) -> str:
    """Fingerprint of the visible form fields, to tell whether Next advanced."""
    try:
        return page.evaluate("""() => Array.from(document.querySelectorAll('input,textarea,select'))
            .filter(e => e.offsetParent !== null).map(e => e.name || e.type).sort().join('|')""")
    except Exception:
        return ""


_FIELD_LABELS = {
    "player_location": "location",
    "others_course_specialization": "course specialization",
    "player_firstname": "first name",
    "player_name_last": "last name",
}


def _missing_required(page) -> list[str]:
    """Friendly names of visible required fields that are still empty."""
    try:
        names = page.evaluate("""() => Array.from(document.querySelectorAll('input,textarea,select'))
            .filter(e => e.offsetParent !== null && e.required && !String(e.value).trim())
            .map(e => e.name || e.placeholder || e.type)""")
    except Exception:
        names = []
    seen, out = set(), []
    for n in names:
        label = _FIELD_LABELS.get(n, n.replace("player_", "").replace("_", " "))
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out


# Field name/placeholder/id fragments that are Unstop profile fields, not
# open-ended custom questions — excluded from question detection.
_KNOWN_FIELDS = ("player_", "course_duration", "course_specialization", "skill",
                 "location", "email", "phone", "mobile", "resume", "search", "otp")

_LABEL_FOR_JS = r"""
  (el) => {
    let t = '';
    if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) t = l.innerText; }
    if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
    if (!t) t = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
    if (!t) { const p = el.closest('.form-group, .field, .form-field, div');
              if (p) { const lab = p.querySelector('label, .label, .question, .ql-title'); if (lab) t = lab.innerText; } }
    return (t || 'Custom question').replace(/\s+/g, ' ').trim().slice(0, 200);
  }
"""


def _open_questions(page) -> list[dict]:
    """Visible, empty, open-ended custom-question fields on the current step —
    textareas, contenteditable editors, and required free-text inputs that
    aren't one of Unstop's known profile fields. Returns [{label}]."""
    try:
        return page.evaluate(r"""(known) => {
          const labelFor = %s;
          const isKnown = el => {
            const s = ((el.name||'') + ' ' + (el.placeholder||'') + ' ' + (el.id||'')).toLowerCase();
            return known.some(k => s.includes(k));
          };
          const out = [], seen = new Set();
          document.querySelectorAll('textarea, input[type=text], [contenteditable=true]').forEach(el => {
            if (el.offsetParent === null) return;                       // not visible
            const val = (el.value !== undefined ? el.value : el.innerText) || '';
            if (val.trim()) return;                                      // already answered
            const isInput = el.tagName === 'INPUT';
            const required = el.required || el.getAttribute('aria-required') === 'true';
            if (isInput && !required) return;                            // ignore optional inputs
            if (isKnown(el)) return;
            const label = labelFor(el);
            if (seen.has(label)) return; seen.add(label);
            out.push({ label });
          });
          return out;
        }""" % _LABEL_FOR_JS, list(_KNOWN_FIELDS)) or []
    except Exception:
        return []


def _fill_custom_answers(page, answers: dict) -> None:
    """Fill the user's answers into the current step's custom-question fields,
    matching each field to an answer by its label (same labels _open_questions
    handed back)."""
    for el in page.query_selector_all("textarea, input[type=text], [contenteditable=true]"):
        try:
            if not el.is_visible():
                continue
            label = el.evaluate(_LABEL_FOR_JS)
            ans = answers.get(label)
            if ans is None:      # fuzzy match on the first 40 chars
                key = label[:40].lower()
                for q, a in answers.items():
                    if key and (key in q.lower() or q[:40].lower() in label.lower()):
                        ans = a
                        break
            if not ans:
                continue
            if (el.evaluate("e => e.tagName") or "").upper() in ("TEXTAREA", "INPUT"):
                el.fill(ans)
            else:
                el.evaluate("(e, v) => { e.innerText = v; e.dispatchEvent(new Event('input', {bubbles: true})); }", ans)
            page.wait_for_timeout(200)
        except Exception:
            continue


def _upload_resume(page, resume_path: str | None) -> None:
    if not resume_path or not os.path.exists(resume_path):
        return
    try:
        fi = page.query_selector("input[type='file']")
        if fi:
            fi.set_input_files(resume_path)
            page.wait_for_timeout(2500)
    except Exception:
        pass


def _is_success(page) -> bool:
    """True once Unstop confirms the registration.

    On success the form redirects off /register (and /register/edit) back to the
    opportunity page — that redirect is the reliable signal; a text match is a
    backup."""
    url = (page.url or "").lower()
    if "/register" not in url and "/edit" not in url and (
        "/internships/" in url or "/competitions/" in url or "/o/" in url
    ):
        return True
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return False
    return any(m in body for m in SUCCESS_MARKERS)
