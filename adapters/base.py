"""Platform adapter interface.

Everything platform-specific (how to search, how to tell a listing has custom
questions, how to submit an application) lives behind this interface. The server,
LLM layer, persistence and UI are all platform-agnostic — adding a new job site
(Unstop, Naukri, …) means writing one new adapter, nothing else."""
from abc import ABC, abstractmethod

from playwright.sync_api import BrowserContext


class PlatformAdapter(ABC):
    # Short machine name, e.g. "internshala". Shown to the UI and stored on each
    # listing so applies route back to the right platform.
    name: str = "base"
    # Human label for the UI.
    label: str = "Base"
    # Whether this platform supports one-click auto-apply. When False, listings
    # are surfaced as manual "Apply on <platform>" links (search-only support).
    supports_auto_apply: bool = True
    # Login page URL for the manual "Log into <platform>" flow (None = no
    # separate login button; e.g. Internshala uses its own credential flow).
    login_url: str | None = None

    @abstractmethod
    def search(self, context: BrowserContext, filters: dict) -> list[dict]:
        """Return listing dicts with at least url, title, company, stipend."""

    def fetch_details(self, context: BrowserContext, url: str) -> dict:
        """Rich listing details for the in-app detail view — full JD plus any
        structured fields (stipend, duration, skills, perks, about company).

        Scraped by *reading* the listing page only, with no apply click, so it
        doesn't trip platform apply throttles. Default: no extra details."""
        return {}

    @abstractmethod
    def classify(self, context: BrowserContext, url: str) -> dict:
        """Open a listing's apply form and return {jd, questions, profile_incomplete}.
        Run at apply time: no custom questions -> submit directly; questions ->
        hand them back for the user to answer first."""

    @abstractmethod
    def apply(self, context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
        """Submit the application. Returns (success, message)."""

    def try_apply(self, context: BrowserContext, listing: dict, answers: dict) -> dict:
        """Agent-facing apply: submit if possible, else hand back what's needed.

        Returns a dict with `ok` + `message`, and optionally `needs_answers` +
        `questions` (+ `jd`) when the form has open-ended questions the user must
        answer first. Default: probe with classify(), then submit via apply()
        (two form loads). Adapters can override to do it in a single load."""
        if not answers:
            d = self.classify(context, listing["url"])
            if d.get("not_logged_in"):
                return {"ok": False, "message": f"Not logged into {self.label} — reconnect and retry."}
            if d.get("profile_incomplete"):
                return {"ok": False, "message": d.get("block_reason") or f"Complete your {self.label} profile."}
            questions = d.get("questions") or []
            if questions:
                return {"ok": False, "needs_answers": True, "questions": questions,
                        "jd": d.get("jd", ""), "message": f"{len(questions)} custom question(s) to answer"}
        ok, msg = self.apply(context, listing, answers or {})
        return {"ok": ok, "message": msg}

    def sync_applications(self, context: BrowserContext) -> list[dict]:
        """Read the platform's 'my applications' page and return
        [{url, title, company, status}] for status syncing. Default: unsupported."""
        return []
