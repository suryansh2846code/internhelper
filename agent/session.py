"""Local persistent browser profile + one-time platform login for the agent.

Path B keeps the browser (and the user's logins) on the user's own machine. We
use a persistent Chromium profile so a manual login to Internshala/Unstop is
saved on disk and reused across runs — the server never sees platform passwords.

`ensure_platform_login` runs once at agent startup: it opens the profile, checks
whether each platform is already logged in, and if not, opens the login pages and
waits for the user to finish. `open_profile` is the context factory the
BrowserWorker uses to run jobs against that same profile."""
import os

import config


def profile_dir() -> str:
    d = config.AGENT_PROFILE_DIR
    os.makedirs(d, exist_ok=True)
    return d


def open_profile(playwright):
    """A headed, persistent Chromium context (one window, logins persist on disk)."""
    return playwright.chromium.launch_persistent_context(profile_dir(), headless=False)


# ── login checks (mirror how each adapter detects an authenticated session) ──

def _internshala_logged_in(context) -> bool:
    page = context.new_page()
    try:
        page.goto(f"{config.INTERNSHALA_BASE_URL}/student/dashboard",
                  wait_until="domcontentloaded", timeout=20_000)
        return "login" not in (page.url or "").lower()
    except Exception:
        return False
    finally:
        page.close()


def _unstop_logged_in(context) -> bool:
    # Unstop marks an authenticated session with an `access_token` cookie.
    page = context.new_page()
    try:
        page.goto("https://unstop.com/", wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(1500)
        return any(c["name"] == "access_token" and "unstop" in c.get("domain", "")
                   for c in context.cookies())
    except Exception:
        return False
    finally:
        page.close()


_CHECKS = {"internshala": _internshala_logged_in, "unstop": _unstop_logged_in}
_LOGIN_URLS = {
    "internshala": f"{config.INTERNSHALA_BASE_URL}/login/user",
    "unstop": "https://unstop.com/login",
}


def ensure_platform_login(playwright, platforms=None):
    """Open the profile, verify each platform, and pause for a manual login if needed.

    Runs on the main thread before the job loop and closes the context when done,
    so the profile is free for the BrowserWorker to reopen."""
    platforms = platforms or ["internshala", "unstop"]
    context = open_profile(playwright)
    try:
        missing = [p for p in platforms if p in _CHECKS and not _CHECKS[p](context)]
        if not missing:
            print(f"[agent] already logged into: {', '.join(platforms)}")
            return

        for p in missing:
            page = context.new_page()
            try:
                page.goto(_LOGIN_URLS[p], wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass

        print("\n" + "=" * 60)
        print("  One-time setup — log in to these in the browser window:")
        for p in missing:
            print(f"    • {p}")
        print("  Your login is saved to a local profile and reused next time.")
        print("=" * 60)
        input("\n  Press Enter here once you've logged in… ")

        still = [p for p in missing if not _CHECKS[p](context)]
        if still:
            print(f"[agent] note: still not detecting a login for {', '.join(still)}. "
                  "Finish in the browser if needed — jobs for those may fail otherwise.")
        else:
            print("[agent] all set — logins saved.")
    finally:
        context.close()
