import re

from playwright.sync_api import BrowserContext
import config

# Internshala's real apply flow lands on a dedicated form page whose URL
# contains this segment (e.g. /application/form/<slug><id>).
APPLICATION_FORM_MARKER = "/application/form"


def dismiss_blocking_modals(page) -> None:
    """Close Internshala's subscription/upsell overlay that otherwise
    intercepts pointer events and blocks the Apply button click."""
    try:
        close_btn = page.query_selector(
            ".subscription_alert [data-dismiss], "
            ".modal.subscription_alert .close, "
            ".modal.show [data-dismiss].ic-24-cross"
        )
        if close_btn:
            close_btn.click()
            page.wait_for_timeout(500)
    except Exception:
        pass


def apply_block_reason(url: str) -> str | None:
    """Return a human-readable reason if the apply flow was redirected away
    from the listing (blocked), else None."""
    u = url.lower()
    if "/registration" in u or "/register" in u or "/login" in u:
        return "Not logged in — Internshala session expired. Re-login (reset session) and try again."
    if "resume" in u or "profile" in u:
        return "Profile incomplete — complete your Internshala profile before applying."
    return None


def on_application_form(page) -> bool:
    """True once we've reached Internshala's actual application form page."""
    return APPLICATION_FORM_MARKER in (page.url or "").lower()


def proceed_to_application_form(page, timeout_ms: int = 12_000) -> None:
    """Click through the intermediate résumé-review page.

    After the Apply button is clicked, Internshala now routes through a page
    that shows the résumé on the student's profile and a 'Proceed to
    application' button before the real /application/form/ page appears. This
    polls for either the form page or the 'Proceed' button (the résumé page can
    take a moment to load) and clicks through until the form appears. It is a
    no-op when the form is shown directly, and gives up after `timeout_ms` when
    the profile is genuinely incomplete (no button and no form ever appears)."""
    import time
    deadline = time.time() + timeout_ms / 1000
    candidates = (
        lambda: page.get_by_role("button", name=re.compile("proceed to application", re.I)),
        lambda: page.get_by_role("link", name=re.compile("proceed to application", re.I)),
        lambda: page.get_by_text(re.compile("proceed to application", re.I)),
    )
    while time.time() < deadline:
        if on_application_form(page):
            return
        clicked = False
        for get_locator in candidates:
            try:
                loc = get_locator()
                if loc.count() > 0:
                    loc.first.click()
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(2000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            # Neither form nor button yet — the résumé page may still be
            # loading. Wait briefly and re-check instead of giving up.
            page.wait_for_timeout(500)


def _question_text_for(page, el) -> str:
    """Best-effort human-readable label for an open-ended form field."""
    for attr in ("aria-label", "placeholder"):
        v = el.get_attribute(attr)
        if v and len(v.strip()) > 8:
            return v.strip()
    el_id = el.get_attribute("id")
    if el_id:
        lab = page.query_selector(f"label[for='{el_id}']")
        if lab:
            t = (lab.inner_text() or "").strip()
            if t:
                return t
    return "Custom question"


def search_internships(context: BrowserContext, filters: dict) -> list[dict]:
    page = context.new_page()
    url = _build_search_url(filters)
    print(f"[scraper] GET {url}")
    page.goto(url, wait_until="domcontentloaded")

    try:
        page.wait_for_selector(".individual_internship", timeout=20_000)
    except Exception:
        print("[scraper] No listings found on page")
        page.close()
        return []

    cards = page.query_selector_all(".individual_internship")
    limit = int(filters.get("max_listings", 20))
    print(f"[scraper] Found {len(cards)} cards, taking up to {limit}")

    listings = []
    for card in cards[:limit]:
        try:
            title_el   = card.query_selector(".job-internship-name a, .job-title-href, h2 a")
            company_el = card.query_selector(".company-name, .company_name p")
            stipend_el = card.query_selector(".stipend")

            if not title_el:
                continue

            href = title_el.get_attribute("href") or ""
            full_url = f"{config.INTERNSHALA_BASE_URL}{href}" if href.startswith("/") else href

            listings.append({
                "title":   title_el.inner_text().strip(),
                "company": company_el.inner_text().strip() if company_el else "Unknown",
                "url":     full_url,
                "stipend": stipend_el.inner_text().strip() if stipend_el else "Not mentioned",
            })
        except Exception as e:
            print(f"[scraper] Card parse error: {e}")
            continue

    page.close()
    return listings


def _goto_with_retry(page, url: str, attempts: int = 3) -> bool:
    """Navigate to url, retrying on transient aborts (net::ERR_ABORTED).
    Returns True if the page loaded, False if all attempts failed."""
    for i in range(attempts):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            return True
        except Exception as e:
            if "ERR_ABORTED" in str(e) or "Timeout" in str(e):
                page.wait_for_timeout(1500 * (i + 1))
                continue
            raise
    return False


def get_listing_details(context: BrowserContext, url: str) -> dict:
    page = context.new_page()
    if not _goto_with_retry(page, url):
        print(f"[scraper] Failed to load listing after retries: {url}")
        page.close()
        return {"jd": "", "questions": []}

    try:
        page.wait_for_selector("#details_container", timeout=15_000)
    except Exception:
        page.close()
        return {"jd": "", "questions": []}

    # Job description
    jd = ""
    jd_el = page.query_selector(".internship_details")
    if jd_el:
        jd = jd_el.inner_text().strip()

    # Click Apply, then walk the multi-step flow to the application form page.
    # Open-ended custom questions are textareas on that form; a form with none
    # (just the availability radio + optional résumé upload) can be auto-applied.
    questions = []
    try:
        apply_btn = page.query_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button")
        if apply_btn:
            dismiss_blocking_modals(page)
            apply_btn.click()
            page.wait_for_timeout(3000)

            # Route through the intermediate résumé-review page if present.
            proceed_to_application_form(page)

            u = (page.url or "").lower()
            if "/login" in u or "/register" in u or "/registration" in u:
                print("[scraper] Not logged in — session expired")
                page.close()
                return {"jd": jd, "questions": [], "profile_incomplete": False, "not_logged_in": True}

            if on_application_form(page):
                page.wait_for_timeout(1000)  # let the form settle
                for ta in page.query_selector_all("textarea"):
                    # Skip hidden textareas — e.g. the availability question's
                    # 'No (Please specify)' box only shows if you pick 'No'.
                    # Only visible textareas are real open-ended questions.
                    if not ta.is_visible():
                        continue
                    questions.append(_question_text_for(page, ta))
            else:
                # Never reached the form → profile is genuinely incomplete.
                print(f"[scraper] Could not reach application form: {page.url}")
                page.close()
                return {"jd": jd, "questions": [], "profile_incomplete": True}
    except Exception as e:
        print(f"[scraper] Questions load error: {e}")

    page.close()
    return {"jd": jd, "questions": questions}


def _build_search_url(filters: dict) -> str:
    """Build an Internshala search URL.

    Internshala uses path segments joined by '/', with the location/category
    segment first and the keyword segment last, e.g.:
      /internships/work-from-home-internships/keywords-react-frontend/
      /internships/internship-in-bangalore/keywords-python/
    Note: the old comma-joined form (keywords-x,work-from-home-internships)
    now triggers a redirect loop, so it must not be used.
    """
    base = f"{config.INTERNSHALA_BASE_URL}/internships"
    segments = []

    loc = filters.get("location", "").strip().lower()
    if "home" in loc or "remote" in loc or "wfh" in loc:
        segments.append("work-from-home-internships")
    elif loc:
        segments.append(f"internship-in-{loc.replace(' ', '-')}")

    if kw := filters.get("keywords", "").strip():
        slug = kw.replace(" ", "-").lower()
        segments.append(f"keywords-{slug}")

    path = "/".join(segments)
    return f"{base}/{path}/" if path else f"{base}/"
