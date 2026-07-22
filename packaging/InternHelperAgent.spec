# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds 'InternHelper Agent.app' (macOS menu-bar agent).

Bundles Python + Playwright (incl. Chromium, via PLAYWRIGHT_BROWSERS_PATH=0 at
build time) + rumps + the agent code, so a user double-clicks one app."""
import os
from PyInstaller.utils.hooks import collect_all

# SPECPATH is the directory containing this spec (…/packaging); repo root is its parent.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ENTRY = os.path.join(SPECPATH, "run_agent_app.py")

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright", "rumps"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Do NOT bundle Chromium — PyInstaller can't re-codesign the pre-signed
# 'Google Chrome for Testing'. It's downloaded to the user's cache on first run.
datas = [(s, dd) for (s, dd) in datas if ".local-browsers" not in dd]
binaries = [(s, dd) for (s, dd) in binaries if ".local-browsers" not in dd]

# Adapters/scraper are imported dynamically (get_adapter), so name them explicitly.
hiddenimports += [
    "adapters", "adapters.internshala", "adapters.unstop", "adapters.base",
    "scraper", "scraper.internshala",
    "apply", "apply.form_filler",
    "applicant", "applicant.resume_pdf",
    "auth", "auth.session",
    "browser_session", "config", "fpdf", "requests",
]

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="InternHelperAgent",
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="InternHelperAgent")

app = BUNDLE(
    coll,
    name="InternHelper Agent.app",
    icon=None,
    bundle_identifier="dev.suryansh.internhelper.agent",
    info_plist={
        "LSUIElement": True,                 # menu-bar only (no Dock icon)
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleURLTypes": [{
            "CFBundleURLName": "dev.suryansh.internhelper",
            "CFBundleURLSchemes": ["internhelper"],
        }],
    },
)
