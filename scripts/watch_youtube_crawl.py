#!/usr/bin/env python3
"""Live terminal dashboard for YouTube transcript crawl progress.

Usage:
  python watch_youtube_crawl.py
  python watch_youtube_crawl.py --interval 2

Run in a separate terminal while crawl_youtube_transcripts.py --all is running.

  # Cursor integrated Terminal
  python watch_youtube_crawl.py
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

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "references" / "sources" / "youtube"
PROGRESS_LOG = OUT_DIR / "crawl_progress.log"
TRANSCRIPTS_DIR = OUT_DIR / "transcripts"

LINE_TS = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
FOUND_RE = re.compile(r"Found (\d+) videos")
TARGETS_RE = re.compile(r"Targets: (\d+), pending: (\d+)")
OK_RE = re.compile(r"^OK (\S+) \| ([^|]+) \| (.+?) \| (\d+) chars$")
FAIL_RE = re.compile(r"^FAIL (\S+) \| (.+?) \| (.+)$")
START_RE = re.compile(r"^START (\S+) \| ([^|]+) \| (.+)$")
SKIP_RE = re.compile(r"^SKIP (\S+) \| (.+)$")
DONE_RE = re.compile(r"^DONE ok=(\d+) err=(\d+) skip=(\d+)")


@dataclass
class CrawlState:
    total: int = 224
    pending_at_start: int | None = None
    session_skip: int = 0
    session_ok: int = 0
    session_fail: int = 0
    cumulative_ok: int = 0
    cumulative_fail: int = 0
    on_disk: int = 0
    current_id: str | None = None
    current_title: str | None = None
    current_started: datetime | None = None
    session_started: datetime | None = None
    done_line: str | None = None
    recent: list[tuple[str, str, str]] = field(default_factory=list)
    ok_durations_sec: list[float] = field(default_factory=list)


def parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def parse_all_durations(lines: list[str]) -> list[float]:
    start_times: dict[str, datetime] = {}
    durations: list[float] = []
    for line in lines:
        m = LINE_TS.match(line)
        if not m:
            continue
        ts = parse_ts(m.group(1))
        body = m.group(2).strip()
        stm = START_RE.match(body)
        if stm:
            start_times[stm.group(1)] = ts
            continue
        om = OK_RE.match(body)
        if om:
            vid = om.group(1)
            if vid in start_times:
                durations.append((ts - start_times[vid]).total_seconds())
    return durations[-30:]  # recent average for ETA


def parse_log() -> CrawlState:
    state = CrawlState()
    state.on_disk = count_transcript_files()
    if not PROGRESS_LOG.exists():
        return state

    text = PROGRESS_LOG.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    state.ok_durations_sec = parse_all_durations(lines)

    for line in lines:
        m = LINE_TS.match(line)
        if not m:
            continue
        body = m.group(2).strip()
        if OK_RE.match(body):
            state.cumulative_ok += 1
        elif FAIL_RE.match(body):
            state.cumulative_fail += 1

    session_start = 0
    for i, line in enumerate(lines):
        if "] Fetching channel metadata..." in line:
            session_start = i

    session_lines = lines[session_start:]
    start_times: dict[str, datetime] = {}
    finished: set[str] = set()

    for line in session_lines:
        m = LINE_TS.match(line)
        if not m:
            continue
        ts = parse_ts(m.group(1))
        body = m.group(2).strip()

        if body.startswith("Fetching channel metadata"):
            state.session_started = ts
            state.session_skip = state.session_ok = state.session_fail = 0
            state.recent.clear()
            start_times.clear()
            finished.clear()
            state.current_id = None
            state.current_title = None
            state.current_started = None
            state.done_line = None
            continue

        fm = FOUND_RE.search(body)
        if fm:
            state.total = int(fm.group(1))
            continue

        tm = TARGETS_RE.search(body)
        if tm:
            state.pending_at_start = int(tm.group(2))
            continue

        sm = SKIP_RE.match(body)
        if sm:
            state.session_skip += 1
            finished.add(sm.group(1))
            continue

        stm = START_RE.match(body)
        if stm:
            vid, title = stm.group(1), stm.group(3).strip()
            start_times[vid] = ts
            if vid not in finished:
                state.current_id = vid
                state.current_title = title
                state.current_started = ts
            continue

        om = OK_RE.match(body)
        if om:
            vid, title, chars = om.group(1), om.group(3).strip(), om.group(4)
            state.session_ok += 1
            finished.add(vid)
            if state.current_id == vid:
                state.current_id = None
                state.current_title = None
                state.current_started = None
            state.recent.insert(0, ("OK", title, f"{chars} chars"))
            state.recent = state.recent[:8]
            continue

        fm2 = FAIL_RE.match(body)
        if fm2:
            vid, title, err = fm2.group(1), fm2.group(2).strip(), fm2.group(3).strip()
            state.session_fail += 1
            finished.add(vid)
            if state.current_id == vid:
                state.current_id = None
                state.current_title = None
                state.current_started = None
            state.recent.insert(0, ("FAIL", title, err[:60]))
            state.recent = state.recent[:8]
            continue

        dm = DONE_RE.match(body)
        if dm:
            state.done_line = body
            state.current_id = None
            state.current_title = None
            state.current_started = None

    return state


def count_transcript_files() -> int:
    if not TRANSCRIPTS_DIR.exists():
        return 0
    return len(list(TRANSCRIPTS_DIR.glob("*.txt")))


def cumulative_done(state: CrawlState) -> int:
    return max(state.on_disk, state.cumulative_ok)


def format_duration(seconds: float) -> str:
    if seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def eta_text(state: CrawlState) -> str:
    done = cumulative_done(state)
    remaining = max(0, state.total - done)
    if not state.ok_durations_sec or remaining == 0:
        return "—"
    avg = sum(state.ok_durations_sec) / len(state.ok_durations_sec)
    return format_duration(avg * remaining)


def progress_bar(done: int, total: int, width: int = 40, ascii_only: bool = False) -> str:
    if total <= 0:
        ch_e = "-" if ascii_only else "░"
        return "[" + ch_e * width + "]"
    ratio = min(1.0, done / total)
    filled = int(width * ratio)
    ch_f, ch_e = (("#", "-") if ascii_only else ("█", "░"))
    return "[" + ch_f * filled + ch_e * (width - filled) + "]"


def render_plain(state: CrawlState, ascii_only: bool = False) -> str:
    done = cumulative_done(state)
    pct = (done / state.total * 100) if state.total else 0
    bar = progress_bar(done, state.total, ascii_only=ascii_only)

    lines = [
        "YouTube 逐字稿抓取儀表板",
        "=" * 56,
        f"{bar} {done}/{state.total} ({pct:.1f}%)",
        f"累計完成: {done}  |  本輪 OK: {state.session_ok} SKIP: {state.session_skip} FAIL: {state.session_fail}",
        f"預估剩餘: {eta_text(state)}",
        "",
    ]

    if state.done_line:
        lines.append(f"狀態: 批次已結束 — {state.done_line}")
    elif state.current_title:
        elapsed = ""
        if state.current_started:
            elapsed = format_duration((datetime.now(timezone.utc) - state.current_started).total_seconds())
        lines.append(f"進行中: {state.current_title}")
        lines.append(f"影片 ID: {state.current_id}  |  已耗時: {elapsed}")
    else:
        lines.append("進行中: （等待下一支或尚未啟動 crawl）")

    if state.recent:
        lines += ["", "最近完成:", *[f"  [{s}] {t} — {d}" for s, t, d in state.recent]]

    lines += ["", f"log: {PROGRESS_LOG}", "Ctrl+C 離開"]
    return "\n".join(lines)


def build_rich_layout(state: CrawlState):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    done = cumulative_done(state)
    pct = (done / state.total * 100) if state.total else 0
    bar = progress_bar(done, state.total, width=50)

    header = Text.assemble(
        ("YouTube 逐字稿抓取", "bold cyan"),
        "  |  ",
        (f"{done}/{state.total}", "bold green"),
        f" ({pct:.1f}%)  ETA {eta_text(state)}",
    )

    stats = Table.grid(padding=(0, 2))
    stats.add_column(style="bold")
    stats.add_column()
    stats.add_row("進度", bar)
    stats.add_row("累計完成", str(done))
    stats.add_row("本輪 OK", str(state.session_ok))
    stats.add_row("本輪 SKIP", str(state.session_skip))
    stats.add_row("本輪 FAIL", str(state.session_fail))

    if state.done_line:
        current = Panel(f"[green]批次已結束[/green]\n{state.done_line}", title="狀態")
    elif state.current_title:
        elapsed = "—"
        if state.current_started:
            elapsed = format_duration(
                (datetime.now(timezone.utc) - state.current_started).total_seconds()
            )
        current = Panel(
            f"[yellow]{state.current_title}[/yellow]\n"
            f"ID: {state.current_id}\n"
            f"已耗時: {elapsed}",
            title="進行中",
        )
    else:
        current = Panel("[dim]等待 crawl 啟動或處理下一支影片…[/dim]", title="狀態")

    recent_tbl = Table(title="最近", show_header=True, header_style="bold")
    recent_tbl.add_column("狀態", width=6)
    recent_tbl.add_column("標題", ratio=1)
    recent_tbl.add_column("備註", width=18)
    for status, title, detail in state.recent[:6]:
        style = "green" if status == "OK" else "red"
        recent_tbl.add_row(f"[{style}]{status}[/{style}]", title[:48], detail[:18])

    layout = Layout()
    layout.split_column(
        Layout(Panel(header, border_style="cyan"), size=3),
        Layout(stats, size=8),
        Layout(current, size=6),
        Layout(recent_tbl, size=10),
        Layout(Panel(str(PROGRESS_LOG), title="log", border_style="dim"), size=3),
    )
    return layout


def run_dashboard_loop(console, interval: float, ascii_only: bool) -> None:
    """Clear and re-print each tick — works in Cursor integrated Terminal."""
    while True:
        state = parse_log()
        if console is not None:
            console.clear()
            console.print(build_rich_layout(state))
        else:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(render_plain(state, ascii_only=ascii_only) + "\n")
            sys.stdout.flush()
        time.sleep(interval)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    parser = argparse.ArgumentParser(description="Live dashboard for YouTube transcript crawl")
    parser.add_argument("--interval", type=float, default=2.0, help="refresh seconds (default 2)")
    parser.add_argument("--plain", action="store_true", help="ASCII mode without rich")
    args = parser.parse_args()

    try:
        from rich.console import Console

        use_rich = not args.plain
    except ImportError:
        use_rich = False

    ascii_only = args.plain or (
        sys.platform == "win32"
        and sys.stdout.encoding
        and sys.stdout.encoding.lower() != "utf-8"
    )

    console = Console(force_terminal=True) if use_rich and not ascii_only else None

    try:
        run_dashboard_loop(console, args.interval, ascii_only)
    except KeyboardInterrupt:
        if console:
            console.print("\n[dim]儀表板已關閉[/dim]")
        else:
            print("\n儀表板已關閉")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
