"""
Desktop launcher for Summit.

Starts the Uvicorn backend in a background thread, waits for it to become
reachable, then opens a pywebview native window pointed at the local server.
Closing the window shuts the server down cleanly.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time

# ── Resolve paths before anything else ───────────────────────────────────
# When running from PyInstaller, _MEIPASS is the temp extraction folder.
# When running from source, use the directory this file lives in.
if getattr(sys, "frozen", False):
    BUNDLE_DIR = sys._MEIPASS
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

# The web app expects its cwd to be summit-web/
WEB_ROOT = os.path.join(BUNDLE_DIR, "summit-web")
os.chdir(WEB_ROOT)

# Make sure the web app and sibling packages are importable
for _p in [WEB_ROOT, BUNDLE_DIR, os.path.join(BUNDLE_DIR, "colorado-lead-machine"),
           os.path.join(BUNDLE_DIR, "lead-vault")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

if sys.platform == "darwin":
    ICON_PATH = os.path.join(BUNDLE_DIR, "summit.icns")
elif sys.platform == "win32":
    ICON_PATH = os.path.join(BUNDLE_DIR, "summit.ico")
else:
    ICON_PATH = os.path.join(BUNDLE_DIR, "summit.png")
HOST = "127.0.0.1"
PREFERRED_PORT = int(os.environ.get("PORT", "8000"))
STARTUP_TIMEOUT = 15  # seconds


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _find_free_port(host: str, preferred: int) -> int:
    """Return preferred port if free, otherwise let the OS pick one."""
    if not _port_in_use(host, preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float) -> bool:
    """Block until the server accepts TCP connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_in_use(host, port):
            return True
        time.sleep(0.15)
    return False


def _run_server(host: str, port: int) -> None:
    """Start Uvicorn in the current thread (runs forever until force-stopped)."""
    import uvicorn
    uvicorn.run("app.main:app", host=host, port=port, log_level="warning", proxy_headers=False)


def _show_error(title: str, message: str) -> None:
    """Show a native error dialog (or print fallback)."""
    try:
        import webview
        webview.create_window(title, html=f"<h2>{title}</h2><p>{message}</p>",
                              width=450, height=200)
        webview.start(icon=ICON_PATH if os.path.exists(ICON_PATH) else None)
    except Exception:
        print(f"[ERROR] {title}: {message}", file=sys.stderr)


def main() -> None:
    # ── Pre-flight checks ────────────────────────────────────────────────
    try:
        import webview  # noqa: F401
    except ImportError:
        _show_error("Missing dependency",
                    "pywebview is not installed.  Run:  pip install pywebview")
        sys.exit(1)

    port = _find_free_port(HOST, PREFERRED_PORT)

    # ── Start backend in a daemon thread ─────────────────────────────────
    server_thread = threading.Thread(target=_run_server, args=(HOST, port),
                                     daemon=True)
    server_thread.start()

    if not _wait_for_server(HOST, port, STARTUP_TIMEOUT):
        _show_error("Startup timeout",
                    f"The backend did not start within {STARTUP_TIMEOUT}s. "
                    "Check the log for import or configuration errors.")
        sys.exit(1)

    # ── Open the native window ───────────────────────────────────────────
    import webview
    window = webview.create_window(
        "Summit",
        url=f"http://{HOST}:{port}",
        width=1400,
        height=900,
        min_size=(900, 600),
    )
    webview.start()
    # When webview.start() returns, the user closed the window.
    # The daemon server thread dies automatically with the process.


if __name__ == "__main__":
    main()
