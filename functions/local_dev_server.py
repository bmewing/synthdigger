#!/usr/bin/env python
"""
Local HTTP server that dispatches to the DO Functions under functions/packages/music/*,
approximating DO's event/response contract closely enough to exercise real
browser-facing behavior (CORS headers, Set-Cookie/Cookie round-tripping) without an
actual `doctl serverless deploy`. Dev-only - single-threaded is fine here.

Usage:
    python functions/sync_lib.py   # vendor music_embeddings first (or after any change)
    python functions/local_dev_server.py [--port 8787]

Routes: GET/POST http://localhost:<port>/api/music/<function-name>

Set LOCAL_PARQUET_DIR to a directory containing the published parquet files to test
the read-path functions without R2 configured (see cloud.py).
"""
import argparse
import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl

ROOT = Path(__file__).resolve().parent
FUNCTIONS_DIR = ROOT / "packages" / "music"
LIB_DIR = ROOT / "lib"

sys.path.insert(0, str(LIB_DIR))

_function_cache = {}


def _load_function(name):
    if name not in _function_cache:
        path = FUNCTIONS_DIR / name / "__main__.py"
        if not path.exists():
            return None
        spec = importlib.util.spec_from_file_location(f"fn_{name.replace('-', '_')}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _function_cache[name] = mod
    return _function_cache[name]


class Handler(BaseHTTPRequestHandler):
    def _dispatch(self, method):
        parts = urlsplit(self.path)
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) != 3 or segments[0] != "api" or segments[1] != "music":
            self._send(404, {"error": "not found"})
            return

        fn_name = segments[2]
        mod = _load_function(fn_name)
        if mod is None:
            self._send(404, {"error": f"no such function: {fn_name}"})
            return

        query_params = dict(parse_qsl(parts.query))

        body_params = {}
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            raw = self.rfile.read(length)
            try:
                body_params = json.loads(raw.decode("utf-8"))
            except Exception:
                body_params = {}

        event = {
            **query_params,
            **body_params,
            "http": {
                "method": method,
                "path": parts.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
            },
        }

        try:
            resp = mod.main(event, {})
        except Exception as exc:
            self._send(500, {"error": f"function crashed: {exc}"})
            return

        self._send_raw(resp)

    def _send(self, status, body_dict):
        self._send_raw({
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body_dict),
        })

    def _send_raw(self, resp):
        status = resp.get("statusCode", 200)
        headers = resp.get("headers", {}) or {}
        body = resp.get("body", "")
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        body_bytes = body.encode("utf-8") if isinstance(body, str) else (body or b"")

        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if body_bytes:
            self.wfile.write(body_bytes)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    def log_message(self, format, *args):
        sys.stderr.write("[local-dev] " + (format % args) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("localhost", args.port), Handler)
    print(f"Local Functions dev server on http://localhost:{args.port}/api/music/<name>")
    print("Set LOCAL_PARQUET_DIR to test without R2 (see cloud.py).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
