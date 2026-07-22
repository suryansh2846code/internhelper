"""PyInstaller entry point for the packaged menu-bar app.

Chromium is downloaded to the user's cache on first run (agent/_bootstrap.py),
not bundled — bundling the pre-signed 'Google Chrome for Testing' breaks the
app's codesigning."""
from agent.app import main

if __name__ == "__main__":
    main()
