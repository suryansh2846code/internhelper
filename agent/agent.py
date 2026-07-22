"""InternHelper local agent.

Runs on the user's machine. Logs into the account, polls the server for queued
jobs, runs them locally with Playwright (their session, their IP), and reports
results back. This is the 'hands' in the Path-B split — the browser never runs
on the server.

Usage:
  SERVER_URL=https://api.example.com AGENT_EMAIL=you@x.com AGENT_PASSWORD=... \
    python -m agent.agent
"""
import os
import re
import sys
import json
import time
import socket
import tempfile
import threading
import traceback

from agent.client import ServerClient

POLL_INTERVAL = 4          # seconds between polls when idle
APPLY_DELAY = 5            # pause between bulk applies (throttle safety)
HEARTBEAT_SECS = 15        # how often to tell the server we're online

# Durable device key from pairing lives here so re-runs skip pairing.
IDENTITY_PATH = os.path.expanduser("~/.internhelper/agent.json")


def _load_identity() -> dict:
    try:
        with open(IDENTITY_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_identity(data: dict) -> None:
    os.makedirs(os.path.dirname(IDENTITY_PATH), exist_ok=True)
    with open(IDENTITY_PATH, "w") as f:
        json.dump(data, f)


def _connect(server: str | None) -> ServerClient:
    """Resolve auth: stored device key → pairing token → email/password.

    If SERVER_URL isn't set (or is the localhost default) but a previous pairing
    exists, reuse that saved server so `python -m agent.agent` just reconnects."""
    ident = _load_identity()
    key, saved_server = ident.get("agent_key"), ident.get("server")

    default_or_empty = server in (None, "", "http://localhost:8000")
    if key and saved_server and default_or_empty:
        server = saved_server
    server = server or "http://localhost:8000"

    if key and saved_server == server:
        print(f"[agent] using saved device key for {server}")
        return ServerClient.with_key(server, key)

    pair_token = os.getenv("AGENT_PAIR_TOKEN")
    if pair_token:
        client, key = ServerClient.pair(server, pair_token, device_name=socket.gethostname())
        _save_identity({"server": server, "agent_key": key})
        print("[agent] paired — device key saved to ~/.internhelper/agent.json")
        return client

    email, password = os.getenv("AGENT_EMAIL"), os.getenv("AGENT_PASSWORD")
    if email and password:
        return ServerClient.login(server, email, password)

    # Interactive fallback — the packaged console app (and a plain terminal run)
    # ask for the pairing code instead of requiring env vars.
    try:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        interactive = False
    if interactive:
        return _pair_interactive(server)

    sys.exit("No credentials. Set AGENT_PAIR_TOKEN (from the web app's Connect panel), "
             "or AGENT_EMAIL + AGENT_PASSWORD.")


def _pair_interactive(server: str) -> ServerClient:
    """Prompt for the pairing code (accepts the whole 'SERVER_URL=… AGENT_PAIR_TOKEN=…'
    command or just the code) and pair this device."""
    print("\n" + "=" * 60)
    print("  Connect this computer to InternHelper")
    print("  Web app → 'Connect your computer' → copy the pairing code.")
    print("=" * 60)
    while True:
        raw = input("\nPaste the pairing code (or full command): ").strip()
        if not raw:
            continue
        token = raw
        if "AGENT_PAIR_TOKEN=" in raw:                     # pasted the full command
            m = re.search(r"AGENT_PAIR_TOKEN=[\"']?([^\s\"']+)", raw)
            if m:
                token = m.group(1)
            sm = re.search(r"SERVER_URL=[\"']?([^\s\"']+)", raw)
            if sm:
                server = sm.group(1)
        try:
            client, key = ServerClient.pair(server, token, device_name=socket.gethostname())
            _save_identity({"server": server, "agent_key": key})
            print(f"[agent] paired ✓ — device key saved to {IDENTITY_PATH}")
            return client
        except Exception as e:
            print(f"[agent] pairing failed: {e}\nThe code expires in ~15 min — get a fresh one and retry.")


def _start_heartbeat(client: ServerClient) -> None:
    def beat():
        while True:
            client.heartbeat()
            time.sleep(HEARTBEAT_SECS)
    threading.Thread(target=beat, daemon=True).start()


# ── Job handlers ────────────────────────────────────────────────────────────

def handle_search(worker, client, payload: dict) -> dict:
    """payload: {platforms, location, stipend_min, max_per_role, roles:[{role, keywords, resume_id}]}."""
    from adapters import get_adapter, list_platforms
    import time as _t

    platforms = payload.get("platforms") or [p["name"] for p in list_platforms()]
    roles = payload.get("roles") or []

    # Snapshot the stop counter so a "Stop" from the web app (which bumps it)
    # aborts this search between listings.
    try:
        start_seq = client.get_control().get("stop_seq", 0)
    except Exception:
        start_seq = 0

    def stop_requested():
        try:
            return client.get_control().get("stop_seq", 0) != start_seq
        except Exception:
            return False

    def work(context):
        seen, listings, stopped = set(), [], False
        for platform in platforms:
            if stopped:
                break
            adapter = get_adapter(platform)
            for role in roles:
                if stopped:
                    break
                kws = " ".join(role.get("keywords", [])) or role.get("role", "")
                filters = {"keywords": kws, "location": payload.get("location", "work from home"),
                           "stipend_min": payload.get("stipend_min", 0),
                           "max_listings": payload.get("max_per_role", 10)}
                base = {"platform": adapter.name, "matched_role": role.get("role", ""),
                        "resume_id": role.get("resume_id")}
                for r in adapter.search(context, filters):
                    if stop_requested():
                        stopped = True
                        break
                    if r["url"] in seen:
                        continue
                    seen.add(r["url"])
                    if not adapter.supports_auto_apply:
                        listings.append({**r, **base, "status": "link", "reason": f"Apply on {adapter.label}"})
                        continue
                    # Just READ each listing page for full details — no Apply click.
                    # Clicking Apply on every listing here is what tripped
                    # Internshala's rate-limiting; that check now happens on demand
                    # at apply time. Every auto-apply listing starts as 'auto'.
                    _t.sleep(1.0)   # gentle pacing between detail page loads
                    info = adapter.fetch_details(context, r["url"])
                    listings.append({**r, **base, **info, "status": "auto"})
        return listings

    return {"listings": worker.run(work)}


def handle_apply(worker, client, payload: dict) -> dict:
    """payload: {listing:{...}, resume_id, answers?}.

    First attempt (no answers): peek at the apply form. If it has open-ended
    custom questions, hand them back as needs_answers so the user can answer them
    instead of submitting blank; otherwise submit straight through. A second call
    carrying the user's answers skips the check and submits."""
    from adapters import get_adapter

    listing = dict(payload.get("listing") or {})
    resume_id = payload.get("resume_id") or listing.get("resume_id")
    if resume_id:
        dest = os.path.join(tempfile.gettempdir(), f"resume_{resume_id}")
        try:
            listing["resume_path"] = client.download_resume(resume_id, dest)
        except Exception as e:
            print(f"[agent] résumé download failed: {e}")

    # Per-user apply details (city / course duration) some platforms ask for.
    profile = payload.get("profile") or {}
    if profile.get("location"):
        listing["apply_location"] = profile["location"]
    if profile.get("course_duration"):
        listing["apply_course_duration"] = profile["course_duration"]

    adapter = get_adapter(listing.get("platform"))
    answers = payload.get("answers") or listing.get("final_answers") or {}

    result = worker.run(lambda ctx: adapter.try_apply(ctx, listing, answers))
    ok = result.get("ok")
    if ok:
        result["applications"] = [{
            "url": listing["url"], "title": listing.get("title", ""),
            "company": listing.get("company", ""), "role": listing.get("matched_role", ""),
            "stipend": listing.get("stipend", ""), "platform": listing.get("platform", ""),
            "status": "applied",
        }]
    return result


def handle_sync(worker, client, payload: dict) -> dict:
    """Read each platform's applications and return them for the server to merge."""
    from adapters import list_platforms, get_adapter

    def work(context):
        found = []
        for p in list_platforms():
            adapter = get_adapter(p["name"])
            try:
                for a in adapter.sync_applications(context):
                    found.append({**a, "platform": p["name"]})
            except Exception as e:
                print(f"[agent] sync {p['name']} error: {e}")
        return found

    return {"applications": worker.run(work)}


HANDLERS = {"search": handle_search, "apply": handle_apply, "sync": handle_sync}


# ── Job loop (shared by the terminal agent and the menu-bar app) ─────────────

def _interruptible_sleep(secs: float, stop_event) -> None:
    if stop_event is None:
        time.sleep(secs)
        return
    end = time.time() + secs
    while time.time() < end and not stop_event.is_set():
        time.sleep(0.2)


def run_job_loop(client, worker, stop_event=None, log=print) -> None:
    """Claim → run → report, until stop_event is set (or forever)."""
    log("[agent] waiting for jobs…")
    while stop_event is None or not stop_event.is_set():
        try:
            job = client.claim_job()
        except Exception as e:
            log(f"[agent] claim error: {e}")
            _interruptible_sleep(POLL_INTERVAL, stop_event)
            continue
        if not job:
            _interruptible_sleep(POLL_INTERVAL, stop_event)
            continue

        log(f"[agent] job {job['id']} ({job['kind']}) — running")
        handler = HANDLERS.get(job["kind"])
        try:
            if not handler:
                client.report(job["id"], "failed", error=f"unknown job kind {job['kind']}")
                continue
            result = handler(worker, client, job.get("payload") or {})
            client.report(job["id"], "done", result=result)
            log(f"[agent] job {job['id']} done")
        except Exception as e:
            traceback.print_exc()
            client.report(job["id"], "failed", error=str(e))


# ── Terminal entrypoint ──────────────────────────────────────────────────────

def _terminal_login(worker):
    """Walk the user through logging into each platform, in the worker's ONE
    persistent browser (logins persist on disk and are reused next run).

    A visible browser window opens on each login page with an InternHelper
    banner; the console prompt is a fallback for people who miss the banner."""
    from agent.session import is_logged_in, open_login_page

    platforms = ["internshala", "unstop"]
    missing = worker.run(lambda ctx: [p for p in platforms if not is_logged_in(ctx, p)])
    if not missing:
        print("[agent] already logged into both platforms ✓")
        return

    print("\n" + "=" * 64)
    print("  ONE-TIME LOGIN — a browser window has opened.")
    print("  Log into each platform there (look for the purple InternHelper bar),")
    print("  then come back here and press Enter.")
    print("=" * 64)
    for p in missing:
        worker.run(lambda ctx, p=p: open_login_page(ctx, p))
        print(f"\n  → A browser window is showing the {p.title()} login page.")
        input(f"    Log in there, then press Enter here to continue… ")
    still = worker.run(lambda ctx: [p for p in missing if not is_logged_in(ctx, p)])
    print(f"[agent] note: still not detecting a login for {', '.join(still)} — "
          "finish in the browser if needed; jobs for those may fail otherwise."
          if still else "[agent] logins saved ✓")


def run_agent(server: str | None, interactive_login: bool = True) -> None:
    """Connect, then run the job loop — starting the loop BEFORE the login
    walkthrough so the web app never sits on 'waiting for agent' while the user
    signs in (the shared browser session means a login applies to jobs at once).
    Shared by the terminal agent and the packaged Windows console app."""
    from browser_session import BrowserWorker
    from agent.session import open_profile
    from agent._bootstrap import ensure_chromium

    client = _connect(server)
    _start_heartbeat(client)
    print(f"[agent] connected to {client.base}")

    print("[agent] preparing the browser (first run downloads it, ~150 MB — please wait)…")
    if not ensure_chromium():
        print("[agent] WARNING: couldn't set up the browser. Check your internet, then re-run.")

    # Jobs AND login share one persistent profile / one browser launch.
    worker = BrowserWorker(context_factory=open_profile)
    stop = threading.Event()
    threading.Thread(target=run_job_loop, args=(client, worker, stop),
                     kwargs={"log": print}, daemon=True).start()
    try:
        if interactive_login and os.getenv("AGENT_SKIP_LOGIN_CHECK") != "1":
            try:
                _terminal_login(worker)
            except Exception as e:
                print(f"[agent] login step error (you can still log in in the browser window): {e}")
        print("\n[agent] Ready. Keep this window open — search & apply from the web app now.\n")
        stop.wait()                      # run until Ctrl+C
    except KeyboardInterrupt:
        print("\n[agent] shutting down")
    finally:
        stop.set()
        worker.close()


def main():
    run_agent(os.getenv("SERVER_URL"))   # server may be None → _connect reuses saved pairing


if __name__ == "__main__":
    main()
