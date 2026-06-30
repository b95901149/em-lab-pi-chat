#!/usr/bin/env python3
"""Backfill manifest.json transcript_path from transcripts/*.txt on disk.

Usage:
  python sync_manifest_transcripts.py
  python sync_manifest_transcripts.py --rebuild-index
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from youtube_process_paths import MANIFEST_PATH, SKILL_ROOT, TRANSCRIPTS_DIR, clear_manifest_cache

ROOT = SKILL_ROOT
VIDEO_ID_RE = re.compile(r"^# video_id: (.+)$", re.M)
SOURCE_RE = re.compile(r"^# source: (.+)$", re.M)
COURSE_RE = re.compile(r"^# course: (.+)$", re.M)
FILENAME_ID_RE = re.compile(r"^([A-Za-z0-9_-]{11})")


def parse_transcript_file(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    header_end = raw.find("\n\n")
    header = raw[:header_end] if header_end > 0 else ""
    body = raw[header_end + 2 :].strip() if header_end > 0 else raw.strip()

    def grab(pattern: re.Pattern[str]) -> str:
        m = pattern.search(header)
        return m.group(1).strip() if m else ""

    vid = grab(VIDEO_ID_RE)
    if not vid:
        m = FILENAME_ID_RE.match(path.stem)
        vid = m.group(1) if m else path.stem.split("_")[0]

    return {
        "video_id": vid,
        "source": grab(SOURCE_RE) or None,
        "course": grab(COURSE_RE) or None,
        "word_count": len(body.replace("\n", " ").split()),
        "char_count": len(body.replace(" ", "")),
        "has_header": bool(VIDEO_ID_RE.search(header)),
        "path": path,
        "rel_path": path.relative_to(ROOT).as_posix(),
    }


def pick_best(files: list[dict]) -> dict:
    return max(
        files,
        key=lambda f: (
            f["has_header"],
            f["word_count"],
            f["char_count"],
        ),
    )


def index_transcripts() -> dict[str, dict]:
    by_id: dict[str, list[dict]] = {}
    for path in sorted(TRANSCRIPTS_DIR.glob("*.txt")):
        info = parse_transcript_file(path)
        by_id.setdefault(info["video_id"], []).append(info)
    return {vid: pick_best(items) for vid, items in by_id.items()}


def recompute_stats(videos: list[dict]) -> dict:
    with_path = 0
    with_file = 0
    for v in videos:
        rel = v.get("transcript_path")
        if not rel:
            continue
        with_path += 1
        if (ROOT / Path(str(rel).replace("\\", "/"))).is_file():
            with_file += 1
    return {
        "total_videos": len(videos),
        "with_transcript": with_file,
        "with_transcript_path": with_path,
        "with_error": sum(1 for v in videos if v.get("error")),
    }


def sync_manifest(rebuild_index: bool) -> int:
    if not MANIFEST_PATH.is_file():
        print(f"manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 1

    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    videos = data.get("videos") or []
    by_id = {v["id"]: v for v in videos if v.get("id")}
    indexed = index_transcripts()

    updated = 0
    course_fixed = 0
    for vid, info in indexed.items():
        entry = by_id.get(vid)
        if not entry:
            continue
        changed = False
        rel = info["rel_path"]
        if entry.get("transcript_path") != rel:
            entry["transcript_path"] = rel
            changed = True
        if info["source"] and entry.get("transcript_source") != info["source"]:
            entry["transcript_source"] = info["source"]
            changed = True
        if info["word_count"] and entry.get("word_count") != info["word_count"]:
            entry["word_count"] = info["word_count"]
            changed = True
        if info["course"] and entry.get("course") != info["course"]:
            entry["course"] = info["course"]
            course_fixed += 1
            changed = True
        if entry.get("error") and info["word_count"] > 20:
            entry["error"] = None
            changed = True
        if changed:
            updated += 1

    orphan_ids = sorted(set(indexed) - set(by_id))
    missing_files = [
        vid
        for vid, entry in by_id.items()
        if entry.get("transcript_path")
        and not (ROOT / Path(str(entry["transcript_path"]).replace("\\", "/"))).is_file()
    ]

    data["videos"] = sorted(by_id.values(), key=lambda v: v.get("title", ""))
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["transcript_stats"] = recompute_stats(data["videos"])
    MANIFEST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_manifest_cache()

    stats = data["transcript_stats"]
    print(f"Indexed transcript files: {len(indexed)}")
    print(f"Manifest entries updated: {updated} (course from header: {course_fixed})")
    print(f"transcript_stats: {stats}")
    if orphan_ids:
        print(f"Transcripts without manifest entry: {len(orphan_ids)} (e.g. {orphan_ids[:3]})")
    if missing_files:
        print(f"Manifest paths missing on disk: {len(missing_files)}")

    if rebuild_index:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "build_youtube_teaching_db.py")],
            check=True,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync manifest transcript_path from disk")
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Also run build_youtube_teaching_db.py",
    )
    args = parser.parse_args()
    return sync_manifest(args.rebuild_index)


if __name__ == "__main__":
    raise SystemExit(main())
