"""Internshala adapter — wraps the existing scraper and form filler.

Kept as a thin wrapper so the proven scraper/form_filler code stays untouched
while conforming to the PlatformAdapter interface."""
from playwright.sync_api import BrowserContext

from adapters.base import PlatformAdapter
from scraper.internshala import search_internships, get_listing_details
from apply.form_filler import submit_application


class InternshalaAdapter(PlatformAdapter):
    name = "internshala"
    label = "Internshala"

    def search(self, context: BrowserContext, filters: dict) -> list[dict]:
        return search_internships(context, filters)

    def classify(self, context: BrowserContext, url: str) -> dict:
        return get_listing_details(context, url)

    def apply(self, context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
        return submit_application(context, listing, answers)
