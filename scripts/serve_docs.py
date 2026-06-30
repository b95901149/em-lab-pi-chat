#!/usr/bin/env python3
"""Serve docs/ with correct MIME types for ES modules (application/javascript)."""

from __future__ import annotations

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Python's default SimpleHTTPRequestHandler may serve .js as text/plain on some
# platforms, which breaks <script type="module"> in Chromium / Edge / Firefox.
MIME_OVERRIDES = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


class DocsHTTPRequestHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        **MIME_OVERRIDES,
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve chat docs with ES module MIME types")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--directory", default=str(DOCS))
    args = parser.parse_args()

    docs_dir = Path(args.directory).resolve()
    if not docs_dir.is_dir():
        print(f"Directory not found: {docs_dir}", file=sys.stderr)
        return 1

    os.chdir(docs_dir)
    server = ThreadingHTTPServer((args.host, args.port), DocsHTTPRequestHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {docs_dir}")
    print(f"Open {url}")
    print("MIME: .js -> application/javascript (required for ES modules)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
