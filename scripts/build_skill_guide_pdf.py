#!/usr/bin/env python3
"""Build 使用說明.pdf for cheng-yu-hsiang-perspective Skill from 使用說明.md."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_course_lite_pdf import build_pdf

SKILL_ROOT = Path(__file__).resolve().parents[1]
MD_PATH = SKILL_ROOT / "使用說明.md"
PDF_PATH = SKILL_ROOT / "使用說明.pdf"


def main() -> int:
    if not MD_PATH.exists():
        print(f"Missing {MD_PATH}")
        return 1
    build_pdf(MD_PATH, PDF_PATH, enable_links=True)
    print(f"Wrote {PDF_PATH}")
    print(f"  size: {PDF_PATH.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
