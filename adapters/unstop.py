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
                    })
        except Exception as e:
            print(f"[unstop] search error: {e}")
        return listings

    def classify(self, context: BrowserContext, url: str) -> dict:
        # Candidate details are pre-filled from the profile; question-detection
        # is deferred to apply(), which bails if it hits an open-ended question.
        return {"jd": "", "questions": [], "profile_incomplete": False}

    def apply(self, context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
        opp_id = listing.get("id") or _id_from_url(listing.get("url", ""))
        if not opp_id:
            return False, "Couldn't determine the Unstop opportunity id."

        page = context.new_page()
        try:
            page.goto(REGISTER_URL.format(id=opp_id), wait_until="domcontentloaded", timeout=40_000)
            page.wait_for_timeout(4000)

            if "/login" in page.url.lower():
                return False, "Not logged into Unstop — log in and retry."

            # Unstop only accepts PDF résumés — convert if needed.
            resume = ensure_pdf(listing.get("resume_path"))

            # Fill the per-application fields Unstop doesn't pull from the profile.
            page.wait_for_timeout(1500)
            _fill_candidate_details(page, listing)

            for _ in range(MAX_STEPS):
                page.wait_for_timeout(1200)

                if _is_success(page):
                    return True, "Registered on Unstop."

                # Open-ended question we can't safely auto-answer -> manual.
                if _has_empty_visible_textarea(page):
                    return False, "Has custom questions — apply on Unstop manually."

                _upload_resume(page, resume)

                # Click the step's main CTA (Next / Update Details / Submit / …),
                # not "Back". This unifies advancing and final submit.
                cta = _find_button(page, PRIMARY_CTA)
                if not cta:
                    return False, "Couldn't find a submit/next button on the Unstop form."

                before = _step_signature(page)
                try:
                    cta.click(timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(3000)

                if _is_success(page):
                    return True, "Registered on Unstop."
                if _step_signature(page) == before:
                    # Didn't advance — a required field is still blocking.
                    missing = _missing_required(page)
                    hint = f" (missing: {', '.join(missing)})" if missing else ""
                    return False, f"Complete your Unstop profile to auto-apply{hint}."
                # advanced to the next step -> loop

            return False, "Unstop form had too many steps — apply manually."
        except Exception as e:
            return False, f"Error applying on Unstop: {e}"
        finally:
            page.close()


# ── helpers ────────────────────────────────────────────────────────────────────

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
    """Fill Unstop's per-application fields: location, course duration, skills."""
    # Location — type the city and pick the matching autocomplete suggestion.
    if config.USER_LOCATION:
        try:
            loc = page.wait_for_selector("input[name='player_location']", timeout=8000)
        except Exception:
            loc = None
        if loc and not (loc.input_value() or "").strip():
            for _ in range(2):  # retry — the suggestion must be clicked to register
                try:
                    loc.click()
                    loc.fill("")
                    loc.type(config.USER_LOCATION, delay=90)
                    page.wait_for_timeout(2600)
                    _click_suggestion(page, config.USER_LOCATION)
                    page.wait_for_timeout(800)
                    if (loc.input_value() or "").strip():
                        break
                except Exception:
                    pass

    # Course duration — select the configured radio value (or the only option).
    try:
        dur = config.USER_COURSE_DURATION
        radio = (page.query_selector(f"input[name='course_duration'][value='{dur}']") if dur
                 else page.query_selector("input[name='course_duration']"))
        if radio and not radio.is_checked():
            _click_input(page, radio)
    except Exception:
        pass

    # Skills — add each from the matched résumé's keywords.
    _fill_skills(page, listing.get("skills") or [])

    # Accept the required Terms & Conditions checkbox.
    _accept_terms(page)


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
    """Tick the required Terms & Conditions checkbox (not the newsletter one).

    The real input is visually hidden by custom styling and sits below the fold,
    so we match by surrounding text and click its label[for] after scrolling."""
    for cb in page.query_selector_all("input[type=checkbox]"):
        try:
            if page.evaluate("(e) => e.checked", cb):
                continue
            ctx = (page.evaluate("(e) => (e.closest('label') || e.parentElement || {}).innerText || ''", cb) or "").lower()
            if not any(k in ctx for k in ("term", "agree", "privacy", "registering")):
                continue
            cid = cb.get_attribute("id")
            label = page.query_selector(f"label[for='{cid}']") if cid else None
            if label:
                label.scroll_into_view_if_needed()
                label.click()
            else:
                page.evaluate("(e) => { const l = e.closest('label') || e.parentElement; if (l) l.click(); }", cb)
            page.wait_for_timeout(400)
            return
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


def _has_empty_visible_textarea(page) -> bool:
    try:
        return page.evaluate("""() => Array.from(document.querySelectorAll('textarea'))
            .some(t => t.offsetParent !== null && !t.value.trim())""")
    except Exception:
        return False


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
