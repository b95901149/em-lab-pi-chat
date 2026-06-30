#!/usr/bin/env python3
"""Serve Course Full static site with Referrer-Policy for YouTube embeds."""

from __future__ import annotations

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from youtube_process_paths import WORKSPACE_ROOT

FULL_ROOT = WORKSPACE_ROOT / "chengfred YouTube Course Full"


class FullHTTPRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve Course Full static site")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()

    os.chdir(FULL_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), FullHTTPRequestHandler)
    url = f"http://{args.host}:{args.port}/index.html"
    print(f"Serving {FULL_ROOT}")
    print(f"Open {url}")
    print("Referrer-Policy: strict-origin-when-cross-origin (required for YouTube embeds)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
