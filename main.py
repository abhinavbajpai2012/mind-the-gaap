#!/usr/bin/env python3
"""Mind the GAAP — one command runs everything.

    python3 main.py              start the control room in a browser
    python3 main.py --cli        run headless and print the table
    python3 main.py --cli --company ADI

Builds the document index once, then runs corpus -> cited history -> call-tone
signal -> forecast and reports the twelve challenge figures.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent.aggregator.panel import Panel          # noqa: E402
from agent.pipeline import STAGES, format_table, make_builder, run  # noqa: E402

UI = ROOT / "ui" / "index.html"
ARCH = ROOT / "ui" / "architecture.html"

_state: dict = {"panel": None, "builder": None, "status": "cold", "error": None}
_lock = threading.Lock()


def get_panel() -> Panel:
    """Build the index once; every later run reuses it."""
    with _lock:
        if _state["panel"] is None:
            _state["status"] = "indexing"
            try:
                _state["panel"] = Panel.challenge()
                _state["builder"] = make_builder(_state["panel"])
                _state["status"] = "ready"
            except Exception as exc:
                _state["status"] = "error"
                _state["error"] = str(exc)
                raise
        return _state["panel"]


# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):        # keep the console for the pipeline
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                 # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
        if url.path in ("/architecture", "/architecture.html"):
            return self._send(200, ARCH.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/meta":
            return self._meta()
        if url.path == "/api/backtest":
            return self._backtest()
        if url.path == "/api/run":
            return self._run(parse_qs(url.query))
        self._send(404, b"not found", "text/plain")

    # -- endpoints ----------------------------------------------------------
    def _meta(self) -> None:
        try:
            panel = get_panel()
            payload = {
                "status": "ready",
                "stages": [{"key": k, "label": v} for k, v in STAGES],
                "frozen_at": panel.frozen_at,
                "companies": [
                    {
                        "ticker": t,
                        "name": p.company,
                        "period": next((str(x.period) for x in panel.targets
                                        if x.ticker == t), ""),
                        "documents": len(panel._docs.get(t, [])),
                        "metrics": [x.metric_label for x in panel.targets
                                    if x.ticker == t],
                    }
                    for t, p in sorted(panel.profiles.items())
                ],
            }
        except Exception as exc:
            payload = {"status": "error", "error": str(exc)}
        self._send(200, json.dumps(payload).encode(), "application/json")

    def _backtest(self) -> None:
        """Walk-forward scores per target. Cached on disk; recomputed on demand."""
        import json as _json
        cache = ROOT / "output" / "backtest.json"
        try:
            if cache.exists():
                payload = {"status": "ready", "rows": _json.loads(cache.read_text())}
            else:
                from agent.mlforecast import backtest_report
                rows = backtest_report(get_panel())
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(_json.dumps(rows, indent=1))
                payload = {"status": "ready", "rows": rows}
        except Exception as exc:
            payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        self._send(200, _json.dumps(payload).encode(), "application/json")

    def _run(self, params: dict) -> None:
        """Stream progress as Server-Sent Events, then the finished table."""
        companies = [c for c in params.get("company", []) if c and c != "ALL"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        events: queue.Queue = queue.Queue()

        def emit(stage: str, message: str, extra: dict) -> None:
            events.put({"type": "stage", "stage": stage, "message": message, **extra})

        def worker() -> None:
            try:
                panel = get_panel()
                result = run(panel, companies or None, on_event=emit,
                             builder=_state["builder"])
                events.put({"type": "done", "result": result.to_dict()})
            except Exception as exc:
                events.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        try:
            while True:
                item = events.get()
                if item is None:
                    break
                self.wfile.write(f"data: {json.dumps(item)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# ---------------------------------------------------------------------------
def serve(port: int, open_browser: bool = True) -> int:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Mind the GAAP — control room at {url}")
    print("  Building the document index (~30s on first request)…\n")
    threading.Thread(target=get_panel, daemon=True).start()
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped\n")
    return 0


def cli(companies: list[str] | None, audit: bool) -> int:
    print("\n  Mind the GAAP — building the document index…")
    panel = Panel.challenge()

    width = max(len(label) for _, label in STAGES)
    seen: set[str] = set()

    def emit(stage: str, message: str, extra: dict) -> None:
        if stage not in seen:
            seen.add(stage)
            label = dict(STAGES).get(stage, stage)
            print(f"  ● {label:<{width}}  {message}")

    result = run(panel, companies, on_event=emit)
    print(format_table(result))

    try:
        from agent.workbooks import write_workbooks
        for path in write_workbooks(result, ROOT):
            print(f"  workbook: {path.relative_to(ROOT)}")
    except Exception as exc:
        print(f"\n  workbooks NOT written: {exc}\n")
        return 1

    if audit:
        out = ROOT / "logs" / f"run-{result.started_at.replace(':', '')}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(panel.audit(), encoding="utf-8")
        print(f"  run log: {out.relative_to(ROOT)}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", action="store_true", help="run headless, print the table")
    ap.add_argument("--company", action="append", help="restrict to a company (repeatable)")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--audit", action="store_true", help="write the run log to logs/")
    args = ap.parse_args(argv)

    if args.cli:
        return cli(args.company, args.audit)
    return serve(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
