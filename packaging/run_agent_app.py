"""PyInstaller entry point for the packaged menu-bar app.

Set PLAYWRIGHT_BROWSERS_PATH=0 *before* importing Playwright so it uses the
Chromium bundled inside the .app (installed with the same flag at build time)."""
import os

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

from agent.app import main

if __name__ == "__main__":
    main()
