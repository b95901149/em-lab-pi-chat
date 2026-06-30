#!/usr/bin/env python3
"""Build benchmark report for board OCR runs (multi-resolution)."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from youtube_process_paths import board_ocr_dir

KEYWORDS = [
    "vector",
    "algebra",
    "3d",
    "basis",
    "unit",
    "addition",
    "cross",
    "dot",
    "maxwell",
    "field",
    "trust",
]


def load_runs(video_id: str) -> list[dict]:
    out_dir = board_ocr_dir(video_id)
    runs: list[dict] = []
    if not out_dir.exists():
        return runs
    for fp in sorted(out_dir.glob("board_ocr*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        data["_file"] = fp.name
        runs.append(data)
    return runs


def stats(run: dict, within_sec: float | None = None) -> dict:
    frames = run.get("frames") or []
    if within_sec is not None:
        frames = [f for f in frames if float(f.get("timestamp_sec", 0)) <= within_sec]

    texts = [str(f.get("ocr_text") or "") for f in frames]
    nonempty = [t for t in texts if t.strip()]
    confs = [float(f.get("ocr_confidence") or 0) for f in frames if str(f.get("ocr_text") or "").strip()]
    merged = "\n".join(nonempty).lower()

    kw_hits = {k: bool(re.search(rf"\b{re.escape(k)}", merged)) or k in merged for k in KEYWORDS}
    kw_count = sum(kw_hits.values())

    return {
        "file": run.get("_file", ""),
        "resolution": run.get("resolution", "?"),
        "full": run.get("coverage_end_sec", 0) >= run.get("video_duration_sec", 1) * 0.95,
        "coverage_sec": within_sec if within_sec is not None else run.get("coverage_end_sec", 0),
        "frames": len(frames),
        "nonempty_frames": len(nonempty),
        "unique_pages": run.get("unique_board_pages") if within_sec is None else len(nonempty),
        "total_chars": sum(len(t) for t in nonempty),
        "avg_conf": round(sum(confs) / len(confs), 3) if confs else 0.0,
        "keyword_hits": kw_count,
        "keywords": [k for k, v in kw_hits.items() if v],
        "timing": run.get("timing") or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", default="nocZR2m180M")
    parser.add_argument("--compare-sec", type=float, default=720, help="apples-to-apples window")
    args = parser.parse_args()

    runs = load_runs(args.video_id)
    if not runs:
        print("No board OCR JSON files found.")
        return 1

    all_stats = [stats(r) for r in runs]
    partial_stats = [stats(r, within_sec=args.compare_sec) for r in runs]

    lines = [
        f"# Board OCR Benchmark — {args.video_id}",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## 全量跑次",
        "",
        "| 檔案 | 解析度 | 全講 | 覆蓋秒數 | 幀數 | 非空幀 | 字元總數 | 平均信心 | 關鍵字命中 |",
        "|------|--------|------|----------|------|--------|----------|----------|------------|",
    ]
    for s in all_stats:
        lines.append(
            f"| {s['file']} | {s['resolution']} | {s['full']} | {s['coverage_sec']:.0f} | "
            f"{s['frames']} | {s['nonempty_frames']} | {s['total_chars']} | {s['avg_conf']} | "
            f"{s['keyword_hits']}/ {len(KEYWORDS)} |"
        )

    lines += [
        "",
        f"## 同區間對照（0–{args.compare_sec:.0f}s）",
        "",
        "| 檔案 | 解析度 | 非空幀 | 字元總數 | 平均信心 | 關鍵字 |",
        "|------|--------|--------|----------|----------|--------|",
    ]
    for s in partial_stats:
        kw = ", ".join(s["keywords"][:6]) or "—"
        lines.append(
            f"| {s['file']} | {s['resolution']} | {s['nonempty_frames']} | {s['total_chars']} | "
            f"{s['avg_conf']} | {kw} |"
        )

    lines += [
        "",
        "## 耗時（有 timing 欄位者）",
        "",
        "| 檔案 | 下載(s) | OCR(s) | 總計(s) | 每幀(s) |",
        "|------|---------|--------|--------|---------|",
    ]
    for s in all_stats:
        t = s["timing"]
        if not t:
            lines.append(f"| {s['file']} | — | — | — | — |")
        else:
            lines.append(
                f"| {s['file']} | {t.get('download_sec', '—')} | {t.get('ocr_sec', '—')} | "
                f"{t.get('total_sec', '—')} | {t.get('sec_per_frame', '—')} |"
            )

    lines += [
        "",
        "## 解讀",
        "",
        "- **關鍵字**：vector, algebra, 3d, basis, unit, addition, cross, dot, maxwell, field, trust",
        "- 公式（hat、分數、根號）仍建議靠 ASR 逐字稿，不靠 OCR。",
        "- 720p 通常是 CP 值甜蜜點；1080p 對英文板書標題有邊際改善。",
        "",
    ]

    out = board_ocr_dir(args.video_id) / "benchmark.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
