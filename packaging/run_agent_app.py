"""PyInstaller entry point for the packaged menu-bar app.

Chromium is downloaded to the user's cache on first run (agent/_bootstrap.py),
not bundled — bundling the pre-signed 'Google Chrome for Testing' breaks the
app's codesigning.

Run with `--check` to verify the bundled Playwright driver works, then exit."""
import sys

from agent.app import main

if __name__ == "__main__":
    if "--check" in sys.argv:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                print("DRIVER OK; chromium exec path:", pw.chromium.executable_path)
        except Exception as e:
            print("DRIVER ERROR:", repr(e))
        from agent._bootstrap import chromium_present
        print("chromium_present:", chromium_present())
        # Import the full search/apply path so a missing dep (e.g. rich) fails
        # the check here rather than at apply time in a user's hands.
        try:
            from adapters import get_adapter, list_platforms
            for p in list_platforms():
                get_adapter(p["name"])
            import apply.form_filler  # noqa: F401
            print("RUNTIME IMPORTS OK:", ", ".join(p["name"] for p in list_platforms()))
        except Exception as e:
            print("RUNTIME IMPORT ERROR:", repr(e))
        sys.exit(0)
    main()
