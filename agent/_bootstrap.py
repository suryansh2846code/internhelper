"""First-run helpers for the packaged app.

A frozen .app may not ship with Chromium (to keep the download smaller). On first
launch we make sure Playwright's Chromium is present, downloading it if needed."""
import os
import sys
import subprocess


def chromium_present() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
        return bool(path) and os.path.exists(path)
    except Exception:
        return False


def ensure_chromium(log=print) -> bool:
    """Ensure Chromium is installed; download it once if not. Returns success."""
    if chromium_present():
        return True
    log("[bootstrap] downloading the browser (one-time, ~150 MB)…")
    try:
        # Use the bundled Playwright CLI. In a frozen app sys.executable is the
        # app itself, so call the module explicitly.
        env = dict(os.environ)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       check=True, env=env)
        return chromium_present()
    except Exception as e:
        log(f"[bootstrap] browser download failed: {e}")
        return False
