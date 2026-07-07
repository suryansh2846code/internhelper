import os
from playwright.sync_api import sync_playwright, BrowserContext
import config


def get_context(playwright) -> BrowserContext:
    browser = playwright.chromium.launch(headless=False)
    if os.path.exists(config.SESSION_PATH):
        context = browser.new_context(storage_state=config.SESSION_PATH)
        # Verify session is still valid
        if _session_valid(context):
            print("[auth] Loaded saved session.")
            return context
        else:
            print("[auth] Saved session expired — logging in again.")
            os.remove(config.SESSION_PATH)
            context.close()

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


def _login_with_captcha_pause(context: BrowserContext):
    page = context.new_page()
    page.goto(f"{config.INTERNSHALA_BASE_URL}/login/user")

    # Fill credentials automatically
    page.wait_for_selector("#email", timeout=10_000)
    page.fill("#email", config.INTERNSHALA_EMAIL)
    page.fill("#password", config.INTERNSHALA_PASSWORD)

    print("\n" + "="*55)
    print("  Browser is open with your credentials filled in.")
    print("  Please solve the CAPTCHA and click Login.")
    print("  This window will close automatically after login.")
    print("="*55 + "\n")

    # Wait up to 2 minutes for user to solve CAPTCHA and land on dashboard
    page.wait_for_url("**/student/dashboard**", timeout=120_000)
    page.close()
