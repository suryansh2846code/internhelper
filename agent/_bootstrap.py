"""First-run helpers for the packaged app.

A frozen .app may not ship with Chromium (to keep the download smaller). On first
launch we make sure Playwright's Chromium is present, downloading it if needed."""
import os
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
    """Ensure Chromium is installed; download it once if not. Returns success.

    Drives Playwright's bundled node CLI directly (compute_driver_executable), so
    it works inside a frozen .app where sys.executable is the app, not python."""
    if chromium_present():
        return True
    log("[bootstrap] downloading the browser (one-time, ~150 MB)…")
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        node, cli = compute_driver_executable()
        subprocess.run([node, cli, "install", "chromium"], check=True, env=get_driver_env())
        return chromium_present()
    except Exception as e:
        log(f"[bootstrap] browser download failed: {e}")
        return False
