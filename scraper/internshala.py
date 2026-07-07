from playwright.sync_api import BrowserContext
import config


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


def get_listing_details(context: BrowserContext, url: str) -> dict:
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")

    try:
        page.wait_for_selector("#details_container", timeout=15_000)
    except Exception:
        page.close()
        return {"jd": "", "questions": []}

    jd = ""
    jd_el = page.query_selector(".internship_details")
    if jd_el:
        jd = jd_el.inner_text().strip()

    # Try to read questions from the server-rendered page
    questions = []
    q_els = page.query_selector_all(".application_question p, .form-group label")
    for q in q_els:
        text = q.inner_text().strip()
        if text and len(text) > 8:
            questions.append(text)

    page.close()
    return {"jd": jd, "questions": questions}


def _build_search_url(filters: dict) -> str:
    base  = f"{config.INTERNSHALA_BASE_URL}/internships"
    parts = []

    if kw := filters.get("keywords", "").strip():
        slug = kw.replace(" ", "-").lower()
        parts.append(f"keywords-{slug}")

    loc = filters.get("location", "").strip().lower()
    if "home" in loc or "remote" in loc or "wfh" in loc:
        parts.append("work-from-home-internships")
    elif loc:
        parts.append(f"location-{loc.replace(' ', '-')}")

    return base + ("/" + ",".join(parts) if parts else "")
