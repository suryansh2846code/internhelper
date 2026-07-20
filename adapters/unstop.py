"""Unstop adapter.

Search runs against Unstop's public JSON API (no login needed). Auto-apply is
not implemented yet — it requires an Unstop account and their apply flow — so
listings are surfaced as manual "Apply on Unstop" links for now."""
from urllib.parse import quote

from playwright.sync_api import BrowserContext

from adapters.base import PlatformAdapter

SEARCH_API = "https://unstop.com/api/public/opportunity/search-result"


class UnstopAdapter(PlatformAdapter):
    name = "unstop"
    label = "Unstop"
    supports_auto_apply = False  # search-only until the apply flow is built

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
                    listings.append({
                        "title": (it.get("title") or "").strip(),
                        "company": (it.get("organisation") or {}).get("name", "Unknown"),
                        "url": it.get("seo_url") or f"https://unstop.com/{it.get('public_url', '')}",
                        "stipend": _stipend(it.get("jobDetail") or {}),
                    })
        except Exception as e:
            print(f"[unstop] search error: {e}")
        return listings

    def classify(self, context: BrowserContext, url: str) -> dict:
        # Auto-apply isn't supported yet, so listings are handed off as links.
        return {"jd": "", "questions": [], "profile_incomplete": False}

    def apply(self, context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
        return False, "Auto-apply for Unstop isn't available yet — apply on Unstop directly."


def _stipend(job_detail: dict) -> str:
    """Human-readable stipend from Unstop's jobDetail block."""
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
