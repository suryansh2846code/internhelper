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

    @abstractmethod
    def search(self, context: BrowserContext, filters: dict) -> list[dict]:
        """Return listing dicts with at least url, title, company, stipend."""

    @abstractmethod
    def classify(self, context: BrowserContext, url: str) -> dict:
        """Open a listing and return {jd, questions, profile_incomplete}.
        No custom questions -> auto-appliable; questions -> apply manually."""

    @abstractmethod
    def apply(self, context: BrowserContext, listing: dict, answers: dict) -> tuple[bool, str]:
        """Submit the application. Returns (success, message)."""
