"""Internshala adapter — wraps the existing scraper and form filler.

Kept as a thin wrapper so the proven scraper/form_filler code stays untouched
while conforming to the PlatformAdapter interface."""
from playwright.sync_api import BrowserContext

from adapters.base import PlatformAdapter
from scraper.internshala import search_internships, get_listing_details, get_listing_info
from apply.form_filler import submit_application

APPLICATIONS_URL = "https://internshala.com/student/applications"


class InternshalaAdapter(PlatformAdapter):
    name = "internshala"
    label = "Internshala"

    def search(self, context: BrowserContext, filters: dict) -> list[dict]:
        return search_internships(context, filters)

    def fetch_details(self, context: BrowserContext, url: str) -> dict:
        return get_listing_info(context, url)

    def classify(self, context: BrowserContext, url: str) -> dict:
        return get_listing_details(context, url)

    def apply(self, context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
        return submit_application(context, listing, answers)

    def sync_applications(self, context: BrowserContext) -> list[dict]:
        page = context.new_page()
        try:
            page.goto(APPLICATIONS_URL, wait_until="domcontentloaded", timeout=40_000)
            page.wait_for_timeout(6000)
            if "/login" in (page.url or "").lower():
                print("[internshala] not logged in — can't sync applications")
                return []
            return page.evaluate(r"""() => {
              const norm = u => u.split('?')[0].replace(/\/$/, '');
              const links = Array.from(document.querySelectorAll('a[href*="/internship/detail"]'));
              const seen = new Set(); const out = [];
              for (const a of links) {
                const url = norm(a.href);
                if (seen.has(url)) continue; seen.add(url);
                // row = smallest ancestor holding "Applied on"; widen a bit for the status cell
                let el = a, row = null;
                for (let i = 0; i < 8 && el; i++) { if ((el.innerText||'').includes('Applied on')) { row = el; break; } el = el.parentElement; }
                let region = row;
                for (let i = 0; i < 2 && region && region.parentElement; i++) region = region.parentElement;
                const scan = (region?.innerText || '').replace(/\s+/g, ' ').toLowerCase();
                const parts = (a.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
                let status = 'applied';
                if (/not selected|rejected/.test(scan)) status = 'rejected';
                else if (/hired|you were selected|received an offer/.test(scan)) status = 'offer';
                else if (/shortlist|interview/.test(scan)) status = 'interview';
                else if (/application viewed|under review/.test(scan)) status = 'under review';
                out.push({ url, title: parts[0] || '', company: parts[1] || '', status });
              }
              return out;
            }""")
        except Exception as e:
            print(f"[internshala] sync error: {e}")
            return []
        finally:
            page.close()
