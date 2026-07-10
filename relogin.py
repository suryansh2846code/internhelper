#!/usr/bin/env python3
"""Refresh the saved Internshala session.

Opens a browser window with your credentials pre-filled, waits for you to
solve the CAPTCHA and land on the dashboard, then saves the session so both
the CLI and the web UI can reuse it. Run this whenever apply actions start
redirecting to the login/registration page.

    python relogin.py
"""
import os
from playwright.sync_api import sync_playwright

import config
from auth.session import _login_with_captcha_pause


def main():
    if os.path.exists(config.SESSION_PATH):
        os.remove(config.SESSION_PATH)
        print("Cleared old session.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        _login_with_captcha_pause(context)
        context.storage_state(path=config.SESSION_PATH)
        print(f"\nNew session saved to {config.SESSION_PATH}")
        browser.close()


if __name__ == "__main__":
    main()
