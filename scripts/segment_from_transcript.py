#!/usr/bin/env python3
"""Generate .segments.json from existing transcript text (no video download).

Fast provisional timestamps (character-weighted). When process_lesson / backfill_segments
runs with local MP4, Whisper segments replace these with --force.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from transcript_utils import (
    SEGMENT_SYNC_TEXT,
    SEGMENT_SYNC_WHISPER,
    find_skill_segments,
    find_skill_transcript,
    infer_segment_sync_source,
    parse_transcript_header,
    save_segments_json,
    segments_from_plain_text,
    segments_meta_path,
    sync_transcript_to_lesson,
)
from youtube_process_paths import manifest_by_id


def segment_from_transcript(video_id: str, force: bool = False, quiet: bool = False) -> int:
    if find_skill_segments(video_id) and not force:
        if not quiet:
            print(f"SKIP {video_id} (segments.json exists)")
        return 2

    txt = find_skill_transcript(video_id)
    if not txt:
        if not quiet:
            print(f"FAIL {video_id}: no transcript")
        return 1

    entry = manifest_by_id().get(video_id, {})
    _, body = parse_transcript_header(txt.read_text(encoding="utf-8"))
    segments = segments_from_plain_text(body, entry.get("duration"))
    if not segments:
        if not quiet:
            print(f"FAIL {video_id}: empty body")
        return 1

    out = save_segments_json(txt, segments, sync_source=SEGMENT_SYNC_TEXT)
    sync_transcript_to_lesson(video_id, entry.get("duration"))
    if not quiet:
        print(f"OK {video_id}: {len(segments)} segments -> {out.name}")
    return 0


def iter_targets(course: str | None, force: bool) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for vid, entry in manifest_by_id().items():
        if course and entry.get("course") != course:
            continue
        if not find_skill_transcript(vid):
            continue
        if find_skill_segments(vid) and not force:
            continue
        out.append((vid, entry))
    return out


def migrate_segment_meta(force: bool = False) -> tuple[int, int]:
    wrote = skipped = 0
    for vid in manifest_by_id():
        txt = find_skill_transcript(vid)
        if not txt or not find_skill_segments(vid):
            continue
        meta = segments_meta_path(txt)
        if meta.is_file() and not force:
            skipped += 1
            continue
        segments = json.loads(find_skill_segments(vid).read_text(encoding="utf-8"))
        src = infer_segment_sync_source(segments)
        meta.write_text(json.dumps({"sync_source": src}, ensure_ascii=False, indent=2), encoding="utf-8")
        wrote += 1
    return wrote, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast text-based segments from existing transcripts")
    parser.add_argument("--video-id", help="single video")
    parser.add_argument("--course", help="all transcripts in course missing segments.json")
    parser.add_argument("--all", action="store_true", help="all transcripts missing segments.json")
    parser.add_argument("--migrate-meta", action="store_true", help="write .segments.meta.json for legacy files")
    parser.add_argument("--force", action="store_true", help="overwrite existing segments.json")
    args = parser.parse_args()

    if args.migrate_meta:
        wrote, skipped = migrate_segment_meta(force=args.force)
        print(f"Migrated meta: wrote={wrote}, skipped={skipped}")
        return 0

    if args.video_id:
        return segment_from_transcript(args.video_id, force=args.force)

    if not args.all and not args.course:
        parser.error("Specify --video-id, --course, or --all")

    targets = iter_targets(args.course, args.force)
    ok = skip = err = 0
    print(f"Segmenting {len(targets)} transcript(s)...")
    for vid, _entry in targets:
        rc = segment_from_transcript(vid, force=args.force, quiet=True)
        if rc == 0:
            ok += 1
        elif rc == 2:
            skip += 1
        else:
            err += 1
    print(f"Done: ok={ok}, skip={skip}, errors={err}")
    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(main())
