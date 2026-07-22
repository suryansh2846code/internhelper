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

    sys.exit("No credentials. Set AGENT_PAIR_TOKEN (from the web app's Connect panel), "
             "or AGENT_EMAIL + AGENT_PASSWORD.")


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

    def work(context):
        seen, listings = set(), []
        for platform in platforms:
            adapter = get_adapter(platform)
            for role in roles:
                kws = " ".join(role.get("keywords", [])) or role.get("role", "")
                filters = {"keywords": kws, "location": payload.get("location", "work from home"),
                           "stipend_min": payload.get("stipend_min", 0),
                           "max_listings": payload.get("max_per_role", 10)}
                base = {"platform": adapter.name, "matched_role": role.get("role", ""),
                        "resume_id": role.get("resume_id")}
                for r in adapter.search(context, filters):
                    if r["url"] in seen:
                        continue
                    seen.add(r["url"])
                    if not adapter.supports_auto_apply:
                        listings.append({**r, **base, "status": "link", "reason": f"Apply on {adapter.label}"})
                        continue
                    _t.sleep(2.5)   # pace Apply clicks so Internshala doesn't rate-limit us
                    details = adapter.classify(context, r["url"])
                    q, pi = details.get("questions", []), details.get("profile_incomplete", False)
                    status = "link" if (pi or q) else "auto"
                    reason = (details.get("block_reason") or f"Complete your {adapter.label} profile") if pi \
                        else (f"{len(q)} custom question(s)" if q else "")
                    listings.append({**r, **base, "jd": details.get("jd", ""),
                                     "questions": q, "reason": reason, "status": status})
        return listings

    return {"listings": worker.run(work)}


def handle_apply(worker, client, payload: dict) -> dict:
    """payload: {listing:{...}, resume_id}. Applies and returns the application record."""
    from adapters import get_adapter

    listing = dict(payload.get("listing") or {})
    resume_id = payload.get("resume_id") or listing.get("resume_id")
    if resume_id:
        dest = os.path.join(tempfile.gettempdir(), f"resume_{resume_id}")
        try:
            listing["resume_path"] = client.download_resume(resume_id, dest)
        except Exception as e:
            print(f"[agent] résumé download failed: {e}")

    adapter = get_adapter(listing.get("platform"))
    ok, msg = worker.run(lambda ctx: adapter.apply(ctx, listing, listing.get("final_answers") or {}))
    result = {"ok": ok, "message": msg}
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
    """Ensure both platforms are logged in, using the worker's ONE persistent
    context (no second browser launch on the same profile)."""
    from agent.session import is_logged_in, LOGIN_URLS

    platforms = ["internshala", "unstop"]
    missing = worker.run(lambda ctx: [p for p in platforms if not is_logged_in(ctx, p)])
    if not missing:
        print("[agent] already logged into: " + ", ".join(platforms))
        return

    print("\n" + "=" * 60)
    print("  Log into these in the browser window (one at a time):")
    print("=" * 60)
    for p in missing:
        worker.run(lambda ctx, p=p: ctx.new_page().goto(
            LOGIN_URLS[p], wait_until="domcontentloaded", timeout=30_000))
        input(f"  → Log into {p}, then press Enter here… ")
    still = worker.run(lambda ctx: [p for p in missing if not is_logged_in(ctx, p)])
    print(f"[agent] note: still not detecting {', '.join(still)} — continuing anyway."
          if still else "[agent] logins saved ✓")


def main():
    server = os.getenv("SERVER_URL")   # may be None → _connect reuses saved pairing

    from browser_session import BrowserWorker
    from agent.session import open_profile

    client = _connect(server)
    _start_heartbeat(client)
    print(f"[agent] connected to {client.base}")

    from agent._bootstrap import ensure_chromium
    ensure_chromium()

    # Jobs AND login share one persistent profile / one browser launch.
    worker = BrowserWorker(context_factory=open_profile)
    try:
        if os.getenv("AGENT_SKIP_LOGIN_CHECK") != "1":
            _terminal_login(worker)
        run_job_loop(client, worker)
    except KeyboardInterrupt:
        print("\n[agent] shutting down")
    finally:
        worker.close()


if __name__ == "__main__":
    main()
