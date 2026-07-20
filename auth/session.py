import os

from playwright.sync_api import sync_playwright, BrowserContext
import config


def get_context(playwright) -> BrowserContext:
    # With a valid saved session, search/apply need no interaction. Internshala
    # blocks headless, so run headed. Focus-stealing is avoided at the caller:
    # the BrowserWorker reuses a single tab, and navigating an existing tab does
    # not raise the window — so the window pops up once, then stays put.
    if os.path.exists(config.SESSION_PATH):
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(storage_state=config.SESSION_PATH)
        if _session_valid(context):
            print("[auth] Loaded saved session.")
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
