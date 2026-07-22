"""PyInstaller entry point for the Windows console agent.

A double-click .exe: on first run it prompts for the pairing code (from the web
app's "Connect your computer"), then runs the job loop against a local
persistent browser. Chromium is downloaded on first run, not bundled.

The shared run flow (agent.agent.run_agent) starts the job loop *before* the
login walkthrough, so the web app never sits on "waiting for agent" while you
sign in.

Run with `--check` to validate the bundled driver + runtime imports, then exit."""
import os
import sys

# Baked default so the .exe needs no config; env can still override.
os.environ.setdefault("SERVER_URL", "https://internspace.suryanshdev.xyz")


def _check() -> None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            print("DRIVER OK; chromium exec path:", pw.chromium.executable_path)
    except Exception as e:
        print("DRIVER ERROR:", repr(e))
    from agent._bootstrap import chromium_present
    print("chromium_present:", chromium_present())
    try:
        from adapters import get_adapter, list_platforms
        for p in list_platforms():
            get_adapter(p["name"])
        import apply.form_filler  # noqa: F401
        print("RUNTIME IMPORTS OK:", ", ".join(p["name"] for p in list_platforms()))
    except Exception as e:
        print("RUNTIME IMPORT ERROR:", repr(e))


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
        sys.exit(0)
    try:
        from agent.agent import main
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        input("\nSomething went wrong. Press Enter to close…")   # keep the window open
