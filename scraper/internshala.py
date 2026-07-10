from playwright.sync_api import BrowserContext
import config


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

    # Click Apply to load questions into the modal
    questions = []
    try:
        apply_btn = page.query_selector("#apply_now_button, .top_apply_now_cta, .apply_now_button")
        if apply_btn:
            dismiss_blocking_modals(page)
            apply_btn.click()
            page.wait_for_timeout(3000)

            # Detect a redirect away from the listing (not logged in / profile incomplete)
            reason = apply_block_reason(page.url)
            if reason:
                print(f"[scraper] {reason}")
                page.close()
                return {"jd": jd, "questions": [], "profile_incomplete": True}

            # Wait for questions modal
            try:
                page.wait_for_selector("#questions .modal-body", timeout=5_000)
            except Exception:
                pass

            modal_body = page.query_selector("#questions .modal-body")
            if modal_body:
                page.wait_for_timeout(1500)  # let AJAX finish
                q_els = modal_body.query_selector_all(
                    "label, p.question, .application_question p, .form-group label, textarea"
                )
                for q in q_els:
                    text = q.inner_text().strip()
                    if text and len(text) > 8 and text not in ("Apply now", "Close"):
                        questions.append(text)
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
