import os
import sys
import subprocess
import threading

from playwright.sync_api import sync_playwright, BrowserContext
import config


def _osa(script: str) -> str:
    return subprocess.run(["osascript", "-e", script],
                          capture_output=True, text=True, timeout=3).stdout.strip()


def _frontmost_app() -> str | None:
    """Name of the currently focused macOS app. None on non-macOS or on error."""
    if sys.platform != "darwin":
        return None
    try:
        return _osa('tell application "System Events" to get name of first '
                    'application process whose frontmost is true') or None
    except Exception:
        return None


def _keep_in_background(prev_app: str | None, context: BrowserContext) -> None:
    """Keep the automation browser out of the foreground.

    The window renders over CDP, so Playwright doesn't need it focused. Each new
    page/render pulls Chromium to the front, so a guardian thread watches the
    focused app and, whenever the *automation* browser grabs it, hands focus
    back to whatever you were using. It only acts on the automation browser, so
    it never fights you when you're working in another app. The guardian stops
    when the context closes."""
    if not prev_app or sys.platform != "darwin":
        return
    stop = threading.Event()

    def guardian():
        while not stop.wait(0.4):
            try:
                cur = _osa('tell application "System Events" to get name of first '
                           'application process whose frontmost is true').lower()
            except Exception:
                continue
            # Playwright's browser shows as "Google Chrome for Testing" / "Chromium".
            if "for testing" in cur or cur == "chromium":
                try:
                    _osa(f'tell application "{prev_app}" to activate')
                except Exception:
                    pass

    threading.Thread(target=guardian, daemon=True).start()

    orig_close = context.close

    def close_and_stop(*args, **kwargs):
        stop.set()
        return orig_close(*args, **kwargs)

    context.close = close_and_stop


def get_context(playwright) -> BrowserContext:
    # With a valid saved session, search/apply need no interaction. Internshala
    # blocks headless, so run headed — but Playwright drives the browser over
    # CDP (no OS focus needed), so we hand focus back to your app right after
    # launch. The window opens in the background instead of switching to it.
    if os.path.exists(config.SESSION_PATH):
        prev_app = None if config.BROWSER_FOREGROUND else _frontmost_app()
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(storage_state=config.SESSION_PATH)
        if _session_valid(context):
            print("[auth] Loaded saved session.")
            _keep_in_background(prev_app, context)
            return context
        print("[auth] Saved session expired — logging in again.")
        os.remove(config.SESSION_PATH)
        context.close()
        browser.close()

    # No valid session: must run headed so the user can solve the CAPTCHA.
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    _login_with_captcha_pause(context)
    context.storage_state(path=config.SESSION_PATH)
    print("[auth] Session saved — won't need to log in again.")
    return context


def _session_valid(context: BrowserContext) -> bool:
    page = context.new_page()
    try:
        page.goto(f"{config.INTERNSHALA_BASE_URL}/student/dashboard", timeout=10_000)
        # If redirected to login, session is dead
        return "login" not in page.url
    except Exception:
        return False
    finally:
        page.close()


def _login_with_captcha_pause(context: BrowserContext, timeout_ms: int = 180_000):
    page = context.new_page()
    page.goto(f"{config.INTERNSHALA_BASE_URL}/login/user")

    # Fill credentials automatically
    page.wait_for_selector("#email", timeout=15_000)
    page.fill("#email", config.INTERNSHALA_EMAIL)
    page.fill("#password", config.INTERNSHALA_PASSWORD)

    minutes = round(timeout_ms / 60_000, 1)
    print("\n" + "="*55)
    print("  Browser is open with your credentials filled in.")
    print("  Please solve the CAPTCHA and click Login.")
    print(f"  You have up to {minutes} minutes; the window closes on success.")
    print("="*55 + "\n")

    # Login is done once we leave the login/registration pages (Internshala may
    # land on the dashboard, homepage, or elsewhere — don't require an exact URL).
    page.wait_for_url(
        lambda url: "/login" not in url and "/registration" not in url,
        timeout=timeout_ms,
    )
    page.close()
