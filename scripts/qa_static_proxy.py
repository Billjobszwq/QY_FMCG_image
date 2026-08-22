#!/usr/bin/env python3
"""QA 静态 + /api 代理（模型管理浏览器验收用；仅 127.0.0.1）。"""
from __future__ import annotations

import argparse
import http.server
import socketserver
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_handler(dist: Path, api_target: str):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(dist), **kw)

        def log_message(self, fmt, *args):
            pass

        def _proxy(self):
            url = api_target + self.path
            body = None
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                body = self.rfile.read(length)
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in ("host", "connection")}
            req = urllib.request.Request(url, data=body, headers=headers,
                                         method=self.command)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    payload = r.read()
                    self.send_response(r.status)
                    for k in ("content-type", "set-cookie"):
                        v = r.headers.get(k)
                        if v:
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
            except urllib.error.HTTPError as e:
                payload = e.read()
                self.send_response(e.code)
                ct = e.headers.get("content-type")
                if ct:
                    self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:  # noqa: BLE001
                self.send_error(502, f"proxy error: {e}")

        def do_GET(self):
            if self.path.startswith("/api/"):
                self._proxy()
                return
            super().do_GET()

        def do_POST(self):
            if self.path.startswith("/api/"):
                self._proxy()
                return
            self.send_error(405)

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4180)
    ap.add_argument("--api", default="http://127.0.0.1:8402")
    ap.add_argument("--dist",
                    default=str(REPO_ROOT / "frontend" / "dist"))
    args = ap.parse_args()
    handler = make_handler(Path(args.dist), args.api)
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"[qa-web] dist={args.dist} port={args.port} api={args.api}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
