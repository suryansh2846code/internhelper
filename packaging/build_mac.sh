#!/bin/bash
# Build "InternHelper Agent.app" (macOS). Run from the repo root:
#   bash packaging/build_mac.sh
set -e
cd "$(dirname "$0")/.."

echo "== creating a clean build venv =="
python3 -m venv .buildvenv
source .buildvenv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements-agent.txt pyinstaller

echo "== installing Chromium INTO the package (bundled with the app) =="
PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium

echo "== building the .app =="
pyinstaller --noconfirm --clean packaging/InternHelperAgent.spec

echo
echo "Built: dist/InternHelper Agent.app"
echo "Open it:  open 'dist/InternHelper Agent.app'"
echo
echo "Unsigned apps are blocked by Gatekeeper. To run locally, right-click → Open,"
echo "or clear quarantine:  xattr -dr com.apple.quarantine 'dist/InternHelper Agent.app'"
echo "For distribution, sign + notarize — see packaging/BUILD.md."
