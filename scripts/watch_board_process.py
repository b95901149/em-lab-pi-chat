#!/usr/bin/env python3
"""Live dashboard for batch board processing (FO / RF courses).

Usage:
  python watch_board_process.py
  python watch_board_process.py --log references/sources/youtube/fo_rf_process_progress.log
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent
DEFAULT_LOG = SKILL_ROOT / "references" / "sources" / "youtube" / "fo_rf_process_progress.log"

LINE_TS = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
PLAN_RE = re.compile(r"^PLAN total=(\d+)")
START_RE = re.compile(r"^START \[(\d+)/(\d+)\] (\S+) \| (\S+) \| (.+)$")
OK_RE = re.compile(r"^OK \[(\d+)/(\d+)\] (\S+) \| scenes=(\d+) \| elapsed=(\d+)s")
FAIL_RE = re.compile(r"^FAIL \[(\d+)/(\d+)\] (\S+) \| elapsed=(\d+)s \| (.+)$")
PROGRESS_RE = re.compile(
    r"^PROGRESS done=(\d+)/(\d+) \(([\d.]+)%\) ok=(\d+) fail=(\d+) eta=([\d.]+)min"
)
DONE_RE = re.compile(r"^DONE ok=(\d+) fail=(\d+) elapsed=([\d.]+)min")


@dataclass
class BoardState:
    total: int = 0
    current_idx: int = 0
    current_id: str | None = None
    current_course: str | None = None
    current_title: str | None = None
    ok: int = 0
    fail: int = 0
    pct: float = 0.0
    eta_min: float = 0.0
    done_line: str | None = None
    session_started: datetime | None = None
    recent: list[tuple[str, str]] = field(default_factory=list)


def parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def read_state(log_path: Path) -> BoardState:
    st = BoardState()
    if not log_path.is_file():
        return st
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_TS.match(line.strip())
        if not m:
            continue
        ts_s, body = m.group(1), m.group(2)
        if body.startswith("SESSION START") and st.session_started is None:
            st.session_started = parse_ts(ts_s)
        m = PLAN_RE.match(body)
        if m:
            st.total = int(m.group(1))
            continue
        m = START_RE.match(body)
        if m:
            st.current_idx = int(m.group(1))
            st.total = int(m.group(2))
            st.current_id = m.group(3)
            st.current_course = m.group(4)
            st.current_title = m.group(5)
            continue
        m = OK_RE.match(body)
        if m:
            st.ok = max(st.ok, int(m.group(1)))  # use latest progress
            vid, scenes, elapsed = m.group(3), m.group(4), m.group(5)
            st.recent.append((f"OK {vid}", f"scenes={scenes} {elapsed}s"))
            st.recent = st.recent[-8:]
            continue
        m = FAIL_RE.match(body)
        if m:
            vid, elapsed, err = m.group(3), m.group(4), m.group(5)
            st.recent.append((f"FAIL {vid}", f"{elapsed}s {err[:60]}"))
            st.recent = st.recent[-8:]
            continue
        m = PROGRESS_RE.match(body)
        if m:
            st.current_idx = int(m.group(1))
            st.total = int(m.group(2))
            st.pct = float(m.group(3))
            st.ok = int(m.group(4))
            st.fail = int(m.group(5))
            st.eta_min = float(m.group(6))
            continue
        m = DONE_RE.match(body)
        if m:
            st.done_line = body
            st.ok = int(m.group(1))
            st.fail = int(m.group(2))
    return st


def render(st: BoardState, log_path: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    lines = [
        "",
        "=" * 60,
        f"  Board batch monitor  |  {now}",
        f"  Log: {log_path}",
        "=" * 60,
    ]
    if st.done_line:
        lines.append(f"  STATUS: FINISHED — {st.done_line}")
    elif st.total:
        bar_w = 30
        filled = int(bar_w * st.pct / 100) if st.pct else 0
        bar = "#" * filled + "-" * (bar_w - filled)
        lines.append(f"  Progress: [{bar}] {st.pct:.1f}%")
        lines.append(f"  Lessons: {st.current_idx}/{st.total}  ok={st.ok}  fail={st.fail}  ETA≈{st.eta_min:.0f} min")
        if st.current_id:
            title = (st.current_title or "")[:48]
            lines.append(f"  Current: [{st.current_course}] {st.current_id}")
            lines.append(f"           {title}")
    else:
        lines.append("  Waiting for PLAN line in log…")
    if st.recent:
        lines.append("  Recent:")
        for tag, detail in st.recent[-5:]:
            lines.append(f"    {tag} — {detail}")
    lines.append("=" * 60)
    lines.append("  Ctrl+C to exit")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    log_path = args.log.resolve()

    while True:
        st = read_state(log_path)
        if args.once:
            print(render(st, log_path))
            return 0
        os.system("cls" if os.name == "nt" else "clear")
        print(render(st, log_path))
        if st.done_line:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
