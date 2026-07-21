# InternHelper local agent

The agent runs on the user's own machine and does the browser work (search /
apply / sync) with their logins and their IP. The cloud server never runs a
browser — it just queues jobs the agent claims.

There are two ways to run it.

## 1. Menu-bar app (macOS) — `agent/app.py`

A tray app: pair once with a code from the web app, then it runs in the
background with a status indicator.

```bash
python -m playwright install chromium      # once
pip install -r requirements-agent.txt      # playwright, requests, fpdf2, rumps
python -m agent.app
```

A ⚡ icon appears in the menu bar. Then:

1. In the web app: **Connect your computer** → copy the command (or just the code).
2. Menu bar → **Connect (paste code)…** → paste it → **Connect**.
   (It accepts either the bare token or the whole `SERVER_URL=… AGENT_PAIR_TOKEN=…` line.)
3. Menu bar → **Log into Internshala** / **Log into Unstop** → log in once in the
   browser window that opens. The login is saved to a local profile and reused.

The device key is stored in `~/.internhelper/agent.json`, so next launch connects
automatically. The dashboard shows the computer as **connected** while the app runs.

## 2. Terminal — `agent/agent.py`

Same core, no GUI. Auth resolves as: saved key → pairing token → email/password.

```bash
# First time — pair with a code from the web app:
SERVER_URL=https://internspace.suryanshdev.xyz \
  AGENT_PAIR_TOKEN=<code from Connect panel> python -m agent.agent

# After pairing, just:
SERVER_URL=https://internspace.suryanshdev.xyz python -m agent.agent

# Or with account credentials instead of a pairing code:
SERVER_URL=… AGENT_EMAIL=you@x.com AGENT_PASSWORD=… python -m agent.agent
```

On start it opens a persistent Chromium profile and, if you're not already logged
in, opens the Internshala/Unstop login pages and waits for you to finish
(`AGENT_SKIP_LOGIN_CHECK=1` to skip that check).

## Notes

- **Packaging** into a double-click `.app`/`.exe` (bundling Python + Playwright)
  is Phase D (PyInstaller). Until then, run from source as above.
- The browser must be headed — Internshala/Unstop block headless at apply/dashboard.
