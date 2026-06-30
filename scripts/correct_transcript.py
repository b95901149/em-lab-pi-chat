#!/usr/bin/env python3
"""Apply glossary ASR corrections to skill + YouTubeProcess transcripts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from glossary_utils import build_replacement_pairs, glossary_ids_for_course
from transcript_utils import (
    SEGMENT_SYNC_TEXT,
    find_skill_segments,
    find_skill_transcript,
    load_segment_sync_source,
    parse_transcript_header,
    save_segments_json,
    sync_transcript_to_lesson,
)
from youtube_process_paths import manifest_by_id

EM_LECTURES_1_5 = [
    "nocZR2m180M",  # 1 Vector algebra
    "OwVWrQNqDUY",  # 2 Coordinate systems
    "hIfiilY5HFM",  # 3 Coordinate systems
    "KilzG90kntI",  # 4 Vectors analysis
    "TwwUwKDRY7I",  # 5 Vectors analysis
]


def format_transcript(meta: dict[str, str], body: str) -> str:
    lines: list[str] = []
    if title := meta.get("title"):
        if not title.startswith("#"):
            lines.append(f"# {title}")
    for key in ("video_id", "course", "source", "fetched_at", "glossary_corrected_at"):
        if meta.get(key):
            lines.append(f"# {key}: {meta[key]}")
    for k, v in meta.items():
        if k in ("title", "video_id", "course", "source", "fetched_at", "glossary_corrected_at"):
            continue
        lines.append(f"# {k}: {v}")
    lines.append("")
    lines.append(body)
    return "\n".join(lines).rstrip() + "\n"


def all_transcript_video_ids() -> list[str]:
    return sorted(
        vid
        for vid, entry in manifest_by_id().items()
        if entry.get("transcript_path") or find_skill_transcript(vid)
    )


def correct_video(
    video_id: str,
    pairs: list[tuple[str, str]] | None = None,
    *,
    course: str | None = None,
    dry_run: bool = False,
) -> dict:
    from glossary_utils import apply_corrections, build_replacement_pairs

    entry = manifest_by_id().get(video_id, {})
    course = course or entry.get("course") or "em"
    if pairs is None:
        pairs = build_replacement_pairs(course=course)

    txt_path = find_skill_transcript(video_id)
    if not txt_path:
        return {"video_id": video_id, "status": "skip", "reason": "no transcript"}

    raw = txt_path.read_text(encoding="utf-8")
    meta, body = parse_transcript_header(raw)
    seg_path = find_skill_segments(video_id)
    segments: list[dict] = []
    if seg_path:
        segments = json.loads(seg_path.read_text(encoding="utf-8"))

    body_new, body_counts = apply_corrections(body, pairs)
    seg_counts: dict[str, int] = {}
    segments_new: list[dict] = []
    for seg in segments:
        text = str(seg.get("text") or "")
        fixed, counts = apply_corrections(text, pairs)
        segments_new.append({**seg, "text": fixed})
        for k, v in counts.items():
            seg_counts[k] = seg_counts.get(k, 0) + v

    merged_counts: dict[str, int] = {}
    for src in (body_counts, seg_counts):
        for k, v in src.items():
            merged_counts[k] = merged_counts.get(k, 0) + v

    changed = body_new != body or segments_new != segments
    if not changed:
        return {
            "video_id": video_id,
            "status": "unchanged",
            "title": meta.get("title") or manifest_by_id().get(video_id, {}).get("title"),
            "replacements": {},
        }

    if dry_run:
        return {
            "video_id": video_id,
            "status": "would_change",
            "title": meta.get("title"),
            "replacements": merged_counts,
        }

    meta["glossary_corrected_at"] = datetime.now(timezone.utc).isoformat()
    txt_path.write_text(format_transcript(meta, body_new), encoding="utf-8")
    if segments_new:
        sync_source = load_segment_sync_source(video_id) or SEGMENT_SYNC_TEXT
        save_segments_json(txt_path, segments_new, sync_source=sync_source)

    entry = manifest_by_id().get(video_id, {})
    sync_transcript_to_lesson(video_id, entry.get("duration"))

    return {
        "video_id": video_id,
        "status": "corrected",
        "title": meta.get("title"),
        "path": str(txt_path),
        "replacements": merged_counts,
        "total_hits": sum(merged_counts.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Correct transcripts using glossary ASR rules.")
    parser.add_argument("--video-id", action="append", dest="video_ids")
    parser.add_argument("--em-1-5", action="store_true", help="correct electromagnetics lectures 1–5")
    parser.add_argument("--all", action="store_true", help="correct all transcripts in manifest")
    parser.add_argument("--course", help="force glossary set for all targets (overrides per-video course)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true", help="rebuild YouTubeProcess index + lesson pages")
    args = parser.parse_args()

    video_ids = list(args.video_ids or [])
    if args.em_1_5:
        video_ids.extend(EM_LECTURES_1_5)
    if args.all:
        video_ids.extend(all_transcript_video_ids())
    if not video_ids:
        parser.error("Specify --video-id, --em-1-5, and/or --all")

    if args.course:
        pairs = build_replacement_pairs(course=args.course)
        print(f"Loaded {len(pairs)} rules (forced course={args.course})")
    else:
        pairs = None
        print("Using per-video course glossaries")

    results = []
    for vid in dict.fromkeys(video_ids):
        if pairs is not None:
            res = correct_video(vid, pairs, dry_run=args.dry_run)
        else:
            res = correct_video(vid, dry_run=args.dry_run)
        results.append(res)
        status = res["status"]
        title = res.get("title") or vid
        hits = res.get("total_hits", 0)
        if res.get("replacements"):
            top = sorted(res["replacements"].items(), key=lambda x: -x[1])[:8]
            detail = ", ".join(f"{k}×{v}" for k, v in top)
        else:
            detail = ""
        if status in ("corrected", "would_change") or not args.all:
            print(f"{status:12} {vid} | {title} | {detail}")

    if args.rebuild_index and not args.dry_run:
        from build_youtube_process_index import main as rebuild_index

        rebuild_index()
        print("Rebuilt YouTubeProcess index and lesson pages.")

    corrected = sum(1 for r in results if r["status"] == "corrected")
    unchanged = sum(1 for r in results if r["status"] == "unchanged")
    skipped = sum(1 for r in results if r["status"] == "skip")
    print(f"Done: {corrected} corrected, {unchanged} unchanged, {skipped} skipped / {len(results)} total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
