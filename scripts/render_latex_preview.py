#!/usr/bin/env python3
"""Render standalone .tex body to PNG using matplotlib mathtext (no pdflatex)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt


def parse_tex(tex_path: Path) -> tuple[str, float | None, list[tuple[str, bool]]]:
    """Return title, timestamp_sec, and lines; bool = render as math."""
    text = tex_path.read_text(encoding="utf-8")
    title = ""
    timestamp_sec: float | None = None
    lines: list[tuple[str, bool]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("% timestamp_sec:") or line.startswith("% video_id:") or line.startswith("% scene_index:"):
            if line.startswith("% timestamp_sec:"):
                try:
                    timestamp_sec = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            continue
        if line.startswith("% ") and not title and not line.startswith("% pix2tex"):
            title = line[2:].strip()
            continue
        if not line or line.startswith("%") or line.startswith("\\documentclass"):
            continue
        if line.startswith("\\usepackage") or line in (r"\begin{document}", r"\end{document}"):
            continue
        line = re.sub(r"\\begin\{align\*\}", "", line)
        line = re.sub(r"\\end\{align\*\}", "", line)
        line = line.replace(r"\\", "").strip()
        while True:
            m = re.search(r"\\textbf\{([^}]*)\}", line)
            if not m:
                break
            line = line[: m.start()] + m.group(1) + line[m.end() :]
        if not line:
            continue
        line = re.sub(r"\\quad\b", "   ", line)
        line = re.sub(r"\s*&\s*", " ", line).strip()
        is_math = any(
            tok in line
            for tok in (
                r"\vec", r"\frac", r"\sqrt", r"\cdot", r"\times", r"\pm",
                r"\alpha", r"\beta", r"\theta", r"\pi", r"\omega", r"\Delta",
                r"\lambda", r"\sum", r"\int", r"\hat", "^", "_", "=",
            )
        )
        lines.append((line, is_math))
    return title, timestamp_sec, lines


def render(tex_path: Path, out_png: Path) -> None:
    title, _ts, lines = parse_tex(tex_path)
    fig = plt.figure(figsize=(11, max(4, 0.55 * len(lines) + 1.5)), dpi=180)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.04, 0.04, 0.92, 0.92])
    ax.axis("off")

    y = 0.97
    if title:
        ax.text(0.02, y, title, transform=ax.transAxes, fontsize=14, fontweight="bold", va="top")
        y -= 0.09

    for line, is_math in lines:
        if is_math:
            ax.text(0.02, y, f"${line}$", transform=ax.transAxes, fontsize=13, va="top")
        else:
            ax.text(0.02, y, line, transform=ax.transAxes, fontsize=13, va="top", family="serif")
        y -= 0.08
        if y < 0.02:
            break

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, format="png", bbox_inches="tight", facecolor="white", dpi=180)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tex", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()
    out = args.output or args.tex.with_suffix(".png")
    render(args.tex, out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
