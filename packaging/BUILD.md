# Packaging the agent into a downloadable app (Phase D)

Goal: a new user **downloads one file, opens it, pastes a code** — no terminal,
no Python, no repo. The `.app` bundles Python + Playwright + Chromium + the agent.

## macOS

### 1. Build

```bash
bash packaging/build_mac.sh
```

Produces `dist/InternHelper Agent.app`. It's a menu-bar app (`LSUIElement`), so it
shows a ⚡ icon in the menu bar, not the Dock.

### 2. Test locally (unsigned)

Gatekeeper blocks unsigned apps. To run your own build:

```bash
xattr -dr com.apple.quarantine "dist/InternHelper Agent.app"
open "dist/InternHelper Agent.app"
```

Then: menu bar ⚡ → **Connect (paste code)…** → paste the code from the web app.

### 3. Sign + notarize (for distributing to others)

Needs an Apple Developer account (Developer ID Application cert).

```bash
# Sign
codesign --deep --force --options runtime \
  --sign "Developer ID Application: YOUR NAME (TEAMID)" \
  "dist/InternHelper Agent.app"

# Zip + notarize
ditto -c -k --keepParent "dist/InternHelper Agent.app" InternHelperAgent.zip
xcrun notarytool submit InternHelperAgent.zip \
  --apple-id "you@apple.id" --team-id TEAMID --password APP_SPECIFIC_PW --wait

# Staple the ticket
xcrun stapler staple "dist/InternHelper Agent.app"
```

### 4. Publish + wire the download button

1. Zip the signed app and upload it as a **GitHub Release** asset.
2. Set the server env var so the web app shows a **Download for macOS** button:
   ```
   AGENT_DOWNLOAD_MAC = https://github.com/<you>/internhelper/releases/download/vX/InternHelperAgent.zip
   ```
   (Railway → service → Variables.) When set, the Connect modal shows the download
   button; the terminal command stays as an "advanced / has the repo" fallback.

## Windows / Linux (later)

The agent core is cross-platform; only the tray UI differs. Windows can use a
`pystray`-based variant of `agent/app.py` and `pyinstaller` with `--onedir`.
Not built yet — Windows users use the terminal agent for now.

## Notes

- Chromium is bundled via `PLAYWRIGHT_BROWSERS_PATH=0` at build time and read back
  with the same env at runtime (see `packaging/run_agent_app.py`). The app also
  downloads it on first run as a fallback (`agent/_bootstrap.py`).
- The device key is stored at `~/.internhelper/agent.json`; the browser profile at
  `./data/agent-profile` relative to the app's working dir.
