"""A single long-lived Playwright browser shared across all operations.

sync Playwright is thread-affine — a browser and its pages may only be used from
the thread that created them. So one dedicated worker thread owns the browser +
context and runs every search/apply task from a queue. This keeps all automation
tabs in ONE window (opened once, reused) instead of launching a fresh window per
operation, and lets the window be closed on demand via close()."""
import queue
import threading


class BrowserWorker:
    def __init__(self, context_factory=None):
        # context_factory(playwright) -> BrowserContext. Defaults to the saved-
        # session Internshala context; the Path-B agent passes a persistent
        # local profile instead (agent.session.open_profile).
        self._context_factory = context_factory
        self._tasks: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._playwright = None
        self._context = None

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

        self._playwright = sync_playwright().start()

        while True:
            item = self._tasks.get()
            if item is None:
                break
            fn, box = item
            try:
                # (Re)build the browser if it's missing or was closed (user hit
                # "Close browser window", closed the Chromium window, or it
                # crashed). This makes the worker self-heal instead of reusing a
                # dead context and failing with "browser has been closed".
                self._ensure_context()
                box["result"] = fn(self._context)
            except Exception as e:
                box["error"] = e
            finally:
                box["event"].set()

        self._shutdown()

    def _ensure_context(self):
        """Ensure a live context/browser exists, rebuilding it if closed."""
        if self._context is not None:
            try:
                browser = self._context.browser
                if browser is None:
                    # Persistent context has no separate Browser object; probing
                    # .pages raises once the window/context is gone.
                    _ = self._context.pages
                    return
                if browser.is_connected():
                    return
            except Exception:
                pass  # treat any probe failure as "dead" and rebuild

        # Tear down whatever's left, then build fresh.
        self._close_browser()
        self._context = self._make_context()
        self._install_single_tab(self._context)

    def _make_context(self):
        if self._context_factory is not None:
            return self._context_factory(self._playwright)
        from auth.session import get_context
        return get_context(self._playwright)

    def _install_single_tab(self, context):
        """Keep exactly one tab and reuse it for every operation.

        Creating a tab raises the window (stealing focus); navigating an
        existing tab does not. So we open one persistent "home" tab, make
        context.new_page() always return it, and make its close() a no-op. Every
        search/apply then navigates this single tab instead of spawning new ones,
        so the window stays quietly in the background and never disappears."""
        # A persistent context launches with one page already open — reuse it
        # instead of adding a second blank tab.
        home = context.pages[0] if context.pages else context.new_page()
        home.close = lambda *args, **kwargs: None      # never destroy the home tab
        context.new_page = lambda *args, **kwargs: home

    def _close_browser(self):
        """Close the current context + browser window, ignoring errors."""
        try:
            if self._context is not None:
                browser = self._context.browser
                self._context.close()
                if browser is not None:
                    browser.close()
        except Exception:
            pass
        self._context = None

    def _shutdown(self):
        self._close_browser()
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
