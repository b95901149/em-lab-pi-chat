#!/usr/bin/env python3
"""Migrate flat YouTubeProcess layout -> courses/{course}/{YouTube title}/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from youtube_process_paths import (
    YOUTUBE_PROCESS_ROOT,
    board_crops_dir,
    board_ocr_dir,
    board_work_dir,
    lesson_dir,
    manifest_video,
    process_rel,
    video_path,
    write_lesson_meta,
)

WORKSPACE_ROOT = YOUTUBE_PROCESS_ROOT.parent
OLD_VENV = WORKSPACE_ROOT / ".venv-pix2tex"
NEW_VENV = YOUTUBE_PROCESS_ROOT / ".venv-pix2tex"


def fix_ocr_json(ocr_json: Path, video_id: str) -> None:
    data = json.loads(ocr_json.read_text(encoding="utf-8"))
    for frame in data.get("frames") or []:
        idx = int(frame["index"])
        frame["image_path"] = process_rel(
            board_work_dir(video_id, 1080) / "frames" / f"scene_{idx:04d}.jpg"
        )
        frame["enhanced_path"] = process_rel(
            board_work_dir(video_id, 1080) / "enhanced" / f"scene_{idx:04d}.png"
        )
    ocr_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def migrate_lesson(video_id: str) -> bool:
    try:
        manifest_video(video_id)
    except KeyError:
        print(f"  skip {video_id}: not in manifest")
        return False

    dest = lesson_dir(video_id)
    if dest.exists() and (dest / "meta.json").is_file() and video_path(video_id).is_file():
        print(f"  skip {video_id}: already at {dest.name}")
        return False

    dest.mkdir(parents=True, exist_ok=True)
    write_lesson_meta(video_id)

    # flat layout: videos/{id}/, board/{id}/
    for src_root in (
        YOUTUBE_PROCESS_ROOT / "videos" / video_id,
        YOUTUBE_PROCESS_ROOT / "board" / video_id,
    ):
        if not src_root.exists():
            continue
        for name in ("video_1080p.mp4", "video_720p.mp4", "video_480p.mp4"):
            src = src_root / name
            if src.is_file():
                dst = video_path(video_id) if "1080" in name else dest / name
                if not dst.exists():
                    shutil.move(str(src), str(dst))

        h1080 = src_root / "h1080"
        if h1080.is_dir():
            for sub in ("frames", "enhanced"):
                s = h1080 / sub
                if s.is_dir():
                    d = board_work_dir(video_id, 1080) / sub
                    d.parent.mkdir(parents=True, exist_ok=True)
                    if d.exists():
                        shutil.rmtree(d)
                    shutil.move(str(s), str(d))

        ocr_src = src_root / "ocr"
        if ocr_src.is_dir():
            odest = board_ocr_dir(video_id)
            odest.mkdir(parents=True, exist_ok=True)
            for fp in ocr_src.iterdir():
                dst = odest / fp.name
                if fp.is_file() and not dst.exists():
                    shutil.move(str(fp), str(dst))

        crops_src = src_root / "crops"
        if crops_src.is_dir():
            cdest = board_crops_dir(video_id)
            cdest.mkdir(parents=True, exist_ok=True)
            for fp in crops_src.iterdir():
                dst = cdest / fp.name
                if fp.is_file() and not dst.exists():
                    shutil.move(str(fp), str(dst))

    # already course layout but missing pieces — merge h1080 at lesson/board
    alt_board = dest / "board"
    if (dest / "h1080").is_dir():
        for sub in ("frames", "enhanced"):
            s = dest / "h1080" / sub
            if s.is_dir():
                d = board_work_dir(video_id, 1080) / sub
                d.parent.mkdir(parents=True, exist_ok=True)
                if not d.exists():
                    shutil.move(str(s), str(d))

    ocr_json = board_ocr_dir(video_id) / "board_ocr_1080p_full.json"
    if ocr_json.is_file():
        fix_ocr_json(ocr_json, video_id)

    print(f"  OK {video_id} -> {dest.relative_to(YOUTUBE_PROCESS_ROOT)}")
    return True


def migrate_venv() -> None:
    if NEW_VENV.exists():
        if OLD_VENV.exists() and OLD_VENV.resolve() != NEW_VENV.resolve():
            shutil.rmtree(OLD_VENV, ignore_errors=True)
        return
    if OLD_VENV.is_dir():
        shutil.move(str(OLD_VENV), str(NEW_VENV))
        print(f"Moved venv -> {NEW_VENV}")


def cleanup_empty() -> None:
    for sub in ("videos", "board"):
        p = YOUTUBE_PROCESS_ROOT / sub
        if p.is_dir() and not any(p.rglob("*")):
            shutil.rmtree(p, ignore_errors=True)


def discover_video_ids() -> list[str]:
    ids: set[str] = set()
    videos_root = YOUTUBE_PROCESS_ROOT / "videos"
    board_root = YOUTUBE_PROCESS_ROOT / "board"
    if videos_root.is_dir():
        ids.update(p.name for p in videos_root.iterdir() if p.is_dir())
    if board_root.is_dir():
        ids.update(p.name for p in board_root.iterdir() if p.is_dir())

    courses = YOUTUBE_PROCESS_ROOT / "courses"
    if courses.is_dir():
        for meta in courses.rglob("meta.json"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                ids.add(data["video_id"])
            except (json.JSONDecodeError, KeyError):
                pass
    return sorted(ids)


def main() -> int:
    YOUTUBE_PROCESS_ROOT.mkdir(parents=True, exist_ok=True)
    migrate_venv()
    ids = discover_video_ids()
    if not ids:
        ids = ["nocZR2m180M"]
    for vid in ids:
        migrate_lesson(vid)
    cleanup_empty()
    print(f"Done. Root: {YOUTUBE_PROCESS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
