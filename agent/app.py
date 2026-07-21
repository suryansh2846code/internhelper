"""InternHelper menu-bar agent (macOS).

A tray app around the same agent core: pair with a code from the web app, run the
job loop against a local persistent browser, heartbeat so the dashboard shows the
computer online, and offer one-click platform login. No terminal needed.

Run from source:   python -m agent.app
Packaged .app (PyInstaller) comes in Phase D."""
import os
import re
import sys
import socket
import threading
import webbrowser

# Baked-in default so a packaged app needs no config; env can override.
DEFAULT_SERVER = os.getenv("SERVER_URL", "https://internspace.suryanshdev.xyz")

try:
    import rumps
except ImportError:
    sys.exit("The menu-bar app needs 'rumps':\n"
             "  pip install -r requirements-agent.txt   (or: pip install rumps)")

from agent.client import ServerClient
from agent import agent as core
from agent.session import open_profile, goto_login


class AgentApp(rumps.App):
    def __init__(self):
        super().__init__("InternHelper", title="⚡", quit_button="Quit")
        self.server = DEFAULT_SERVER
        self.client = None
        self.worker = None
        self.stop_event = None

        self.status_item = rumps.MenuItem("Starting…")
        self.menu = [
            self.status_item,
            None,
            rumps.MenuItem("Connect (paste code)…", callback=self.on_connect),
            rumps.MenuItem("Log into Internshala", callback=lambda _: self._login("internshala")),
            rumps.MenuItem("Log into Unstop", callback=lambda _: self._login("unstop")),
            None,
            rumps.MenuItem("Open dashboard", callback=self.on_open_dashboard),
        ]

        threading.Thread(target=self._auto_connect, daemon=True).start()
        rumps.Timer(self._refresh_status, 5).start()

    # ── browser worker (lazy) ────────────────────────────────────────────────
    def _ensure_worker(self):
        if self.worker is None:
            from browser_session import BrowserWorker
            self.worker = BrowserWorker(context_factory=open_profile)
        return self.worker

    # ── connection ───────────────────────────────────────────────────────────
    def _auto_connect(self):
        ident = core._load_identity()
        key, server = ident.get("agent_key"), ident.get("server")
        if key and server:
            self.server = server
            self._start(ServerClient.with_key(server, key))

    def _start(self, client):
        self.client = client
        core._start_heartbeat(client)
        self.stop_event = threading.Event()
        threading.Thread(
            target=core.run_job_loop,
            args=(client, self._ensure_worker(), self.stop_event),
            kwargs={"log": self._log}, daemon=True,
        ).start()
        self._refresh_status(None)

    def on_connect(self, _):
        win = rumps.Window(
            message="Paste the pairing code from the web app.\n"
                    "(Connect your computer → copy the whole command or just the code.)",
            title="Connect your computer", ok="Connect", cancel="Cancel",
            dimensions=(360, 90))
        resp = win.run()
        if not resp.clicked:
            return
        raw = (resp.text or "").strip()
        token = raw
        if "AGENT_PAIR_TOKEN=" in raw:          # user pasted the full command
            m = re.search(r"AGENT_PAIR_TOKEN=(\S+)", raw)
            token = m.group(1) if m else raw
            sm = re.search(r"SERVER_URL=(\S+)", raw)
            if sm:
                self.server = sm.group(1)
        if token:
            threading.Thread(target=self._do_pair, args=(token,), daemon=True).start()

    def _do_pair(self, token):
        try:
            client, key = ServerClient.pair(self.server, token, socket.gethostname())
        except Exception as e:
            self._notify("Pairing failed", str(e))
            return
        core._save_identity({"server": self.server, "agent_key": key})
        self._start(client)
        self._notify("Connected", "Your computer is linked. Now log into the platforms.")

    # ── platform login ───────────────────────────────────────────────────────
    def _login(self, platform):
        def work():
            ok = self._ensure_worker().run(lambda ctx: goto_login(ctx, platform))
            self._notify(f"{platform.title()} login",
                         "Looks logged in ✓" if ok
                         else "Log in in the browser window that opened.")
        threading.Thread(target=work, daemon=True).start()

    def on_open_dashboard(self, _):
        webbrowser.open(self.server)

    # ── ui helpers ───────────────────────────────────────────────────────────
    def _refresh_status(self, _):
        host = self.server.split("://")[-1] if self.server else ""
        self.status_item.title = (f"● Connected · {host}" if self.client
                                  else "○ Not connected — click Connect")

    def _notify(self, title, msg):
        try:
            rumps.notification(title, "", msg)
        except Exception:
            pass
        self._log(f"[app] {title}: {msg}")

    def _log(self, msg):
        print(msg, flush=True)


def main():
    AgentApp().run()


if __name__ == "__main__":
    main()
