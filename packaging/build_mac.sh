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

# Chromium is NOT bundled (bundling the pre-signed browser breaks codesigning);
# the app downloads it to the user's cache on first launch. Remove any browsers
# already in the package so PyInstaller's playwright hook can't pull them in.
find .buildvenv -type d -name ".local-browsers" -exec rm -rf {} + 2>/dev/null || true

echo "== building the .app =="
pyinstaller --noconfirm --clean packaging/InternHelperAgent.spec

echo "== zipping for distribution =="
# ditto preserves the .app bundle structure/metadata (unlike plain zip).
( cd dist && ditto -c -k --keepParent "InternHelper Agent.app" "InternHelperAgent.zip" )

echo
echo "Built: dist/InternHelper Agent.app"
echo "Zip:   dist/InternHelperAgent.zip   (upload this as a GitHub Release asset)"
echo "Open it:  open 'dist/InternHelper Agent.app'"
echo
echo "Unsigned apps are blocked by Gatekeeper. To run locally, right-click → Open,"
echo "or clear quarantine:  xattr -dr com.apple.quarantine 'dist/InternHelper Agent.app'"
echo "For distribution, sign + notarize — see packaging/BUILD.md."
