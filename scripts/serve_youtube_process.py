#!/usr/bin/env python3
"""Serve YouTubeProcess with HTTP Range (206) support — required for MP4 seeking."""

from __future__ import annotations

import argparse
import os
import re
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from youtube_process_paths import YOUTUBE_PROCESS_ROOT

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


class RangeHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Static files + byte-range responses for HTML5 video seeking."""

    _range: tuple[int, int] | None = None

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        if not os.path.isfile(path):
            return super().send_head()

        ctype = self.guess_type(path)
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        fs = os.fstat(f.fileno())
        size = fs.st_size
        self._range = None

        range_header = self.headers.get("Range")
        if range_header:
            m = _RANGE_RE.match(range_header.strip())
            if m:
                start_s, end_s = m.groups()
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else size - 1
                end = min(end, size - 1)
                if start < size and start <= end:
                    self.send_response(HTTPStatus.PARTIAL_CONTENT)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(end - start + 1))
                    self.end_headers()
                    f.seek(start)
                    self._range = (start, end)
                    return f

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        if self._range:
            _start, end = self._range
            remaining = end - source.tell() + 1
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
            return
        super().copyfile(source, outputfile)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve YouTubeProcess (Range-enabled)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    os.chdir(YOUTUBE_PROCESS_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), RangeHTTPRequestHandler)
    url = f"http://{args.host}:{args.port}/index.html"
    print(f"Serving {YOUTUBE_PROCESS_ROOT}")
    print(f"Open {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
