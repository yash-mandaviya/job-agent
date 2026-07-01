#!/usr/bin/env python3
"""Serve the jobs dashboard locally with a working Refresh button.

Starts a small localhost-only HTTP server that:
  • serves data/dashboard.html at /
  • POST /run   → runs the full pipeline (python -m src.main --dry-run) in the
                  background and rebuilds the dashboard
  • GET  /status → JSON {running, last_line, last_rc}

Open http://localhost:8765/ and click "Refresh — run full flow".
Everything stays on your machine. Stop with Ctrl-C.

Usage: python scripts/serve_dashboard.py [--port 8765] [--run-args "--dry-run --all"]
"""
from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "data" / "dashboard.html"
sys.path.insert(0, str(ROOT))

state = {"running": False, "last_line": "", "last_rc": None}
_lock = threading.Lock()
RUN_ARGS = ["--dry-run"]  # overridden by --run-args


def run_pipeline() -> None:
    with _lock:
        if state["running"]:
            return
        state.update(running=True, last_line="starting…", last_rc=None)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.main", *RUN_ARGS],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line:
                state["last_line"] = line[:240]
        proc.wait()
        state["last_rc"] = proc.returncode
    except Exception as e:  # noqa: BLE001
        state["last_line"] = f"error: {e}"
        state["last_rc"] = -1
    finally:
        # Always rebuild the dashboard so it refreshes even on an early exit.
        try:
            from src.dashboard import build_dashboard
            build_dashboard()
        except Exception as e:  # noqa: BLE001
            state["last_line"] = f"dashboard build failed: {e}"
        state["running"] = False


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, body, ctype="text/html; charset=utf-8") -> None:
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.split("?")[0] in ("/", "/index.html", "/dashboard.html"):
            if DASH.exists():
                self._send(200, DASH.read_bytes())
            else:
                self._send(200, "<h1>Dashboard not built yet.</h1>"
                                "<p>Click nothing — run <code>python scripts/build_dashboard.py</code> first.</p>")
        elif self.path == "/status":
            self._send(200, json.dumps(state), "application/json")
        else:
            self._send(404, "not found")

    def do_POST(self) -> None:
        if self.path == "/run":
            threading.Thread(target=run_pipeline, daemon=True).start()
            self._send(202, json.dumps({"ok": True}), "application/json")
        else:
            self._send(404, "not found")

    def log_message(self, *args) -> None:  # silence per-request logging
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--run-args", default="--dry-run",
                    help='Args passed to `python -m src.main` (default: "--dry-run").')
    ap.add_argument("--no-open", action="store_true", help="Don't auto-open the browser.")
    args = ap.parse_args()

    global RUN_ARGS
    RUN_ARGS = args.run_args.split()

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as httpd:
        url = f"http://localhost:{args.port}/"
        print(f"dashboard → {url}   (Refresh runs: python -m src.main {args.run_args})")
        print("Ctrl-C to stop.")
        if not args.no_open:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
