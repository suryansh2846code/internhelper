# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds the Windows console agent (InternHelperAgent.exe).

Bundles Python + Playwright + the agent code. Chromium is NOT bundled; it's
downloaded to the user's cache on first run (agent/_bootstrap.py). Build on
Windows (or the GitHub Actions windows runner) — PyInstaller is per-platform."""
import os
from PyInstaller.utils.hooks import collect_all

# SPECPATH is the directory containing this spec (…/packaging); repo root is its parent.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ENTRY = os.path.join(SPECPATH, "run_agent_win.py")

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Don't bundle Chromium — downloaded on first run.
datas = [(s, dd) for (s, dd) in datas if ".local-browsers" not in dd]
binaries = [(s, dd) for (s, dd) in binaries if ".local-browsers" not in dd]

# Dynamically imported modules (get_adapter) — name them explicitly.
hiddenimports += [
    "adapters", "adapters.internshala", "adapters.unstop", "adapters.base",
    "scraper", "scraper.internshala",
    "apply", "apply.form_filler",
    "applicant", "applicant.resume_pdf",
    "auth", "auth.session",
    "browser_session", "config", "fpdf", "requests", "rich", "rich.console",
]

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="InternHelperAgent",
    console=True,                 # console window for the paste-code / login prompts
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="InternHelperAgent")
