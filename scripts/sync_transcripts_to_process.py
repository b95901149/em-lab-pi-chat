#!/usr/bin/env python3
"""Copy Skill transcripts (+ segments) into YouTubeProcess lesson folders."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from transcript_utils import sync_all_transcripts


def main() -> int:
    count = sync_all_transcripts()
    print(f"Synced transcripts for {count} lessons.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
