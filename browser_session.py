"""A single long-lived Playwright browser shared across all operations.

sync Playwright is thread-affine — a browser and its pages may only be used from
the thread that created them. So one dedicated worker thread owns the browser +
context and runs every search/apply task from a queue. This keeps all automation
tabs in ONE window (opened once, reused) instead of launching a fresh window per
operation, and lets the window be closed on demand via close()."""
import queue
import threading


class BrowserWorker:
    def __init__(self):
        self._tasks: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._playwright = None
        self._context = None
        self._alive = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self, fn, timeout: float = 600.0):
        """Run fn(context) on the browser thread and return its result.

        Starts the browser on first use. Tasks are serialized, so a search and a
        later auto-apply share the one window and never touch Playwright
        concurrently."""
        self._ensure_started()
        box = {"event": threading.Event(), "result": None, "error": None}
        self._tasks.put((fn, box))
        if not box["event"].wait(timeout):
            raise TimeoutError("Browser task timed out.")
        if box["error"]:
            raise box["error"]
        return box["result"]

    def close(self):
        """Close the browser window and stop the worker (idempotent).

        If a task is in flight the window closes once it finishes — sync
        Playwright can't be interrupted mid-task safely."""
        with self._lock:
            if not self.is_running():
                return
            thread = self._thread
            self._tasks.put(None)
        thread.join(timeout=15)

    # ── internals ──────────────────────────────────────────────────────────────

    def _ensure_started(self):
        with self._lock:
            if self.is_running():
                return
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self):
        from playwright.sync_api import sync_playwright
        from auth.session import get_context

        self._playwright = sync_playwright().start()
        try:
            self._context = get_context(self._playwright)
            self._alive = True
        except Exception:
            self._alive = False

        while True:
            item = self._tasks.get()
            if item is None:
                break
            fn, box = item
            if not self._alive:
                box["error"] = RuntimeError("Browser failed to start (check login/session).")
                box["event"].set()
                continue
            try:
                box["result"] = fn(self._context)
            except Exception as e:
                box["error"] = e
            finally:
                box["event"].set()

        self._shutdown()

    def _shutdown(self):
        try:
            if self._context is not None:
                browser = self._context.browser
                self._context.close()  # also stops the focus guardian
                if browser is not None:
                    browser.close()
        except Exception:
            pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._playwright = None
        self._alive = False
