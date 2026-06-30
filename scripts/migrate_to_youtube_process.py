#!/usr/bin/env python3
"""One-time migration: move videos + OCR raw assets to YouTubeProcess."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from youtube_process_paths import (
    BOARD_NOTES_DIR,
    YOUTUBE_PROCESS_ROOT,
    board_crops_dir,
    board_ocr_dir,
    board_work_dir,
    process_rel,
    skill_latex_dir,
    video_dir,
)

SKILL_YT = BOARD_NOTES_DIR.parent
OLD_PILOT = SKILL_YT / "board_pilot"
OLD_NOTES = BOARD_NOTES_DIR


def fix_ocr_json_paths(ocr_json: Path) -> None:
    data = json.loads(ocr_json.read_text(encoding="utf-8"))
    for frame in data.get("frames") or []:
        idx = int(frame["index"])
        vid = data["video_id"]
        frame["image_path"] = process_rel(board_work_dir(vid, 1080) / "frames" / f"scene_{idx:04d}.jpg")
        frame["enhanced_path"] = process_rel(board_work_dir(vid, 1080) / "enhanced" / f"scene_{idx:04d}.png")
    ocr_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def migrate_video(video_id: str) -> list[str]:
    moved: list[str] = []
    old_h1080 = OLD_PILOT / video_id / "h1080"
    if not old_h1080.exists():
        return moved

    vdest = video_dir(video_id)
    vdest.mkdir(parents=True, exist_ok=True)
    for name in ("video_1080p.mp4", "video_720p.mp4", "video_480p.mp4"):
        src = old_h1080 / name
        if src.is_file():
            dst = vdest / name
            if not dst.exists():
                shutil.move(str(src), str(dst))
            moved.append(str(dst))

    wdest = board_work_dir(video_id, 1080)
    wdest.mkdir(parents=True, exist_ok=True)
    for sub in ("frames", "enhanced"):
        src = old_h1080 / sub
        if src.is_dir():
            dst = wdest / sub
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(src), str(dst))
            moved.append(str(dst))

    odest = board_ocr_dir(video_id)
    odest.mkdir(parents=True, exist_ok=True)
    note_src = OLD_NOTES / video_id
    if note_src.is_dir():
        for pattern in ("board_ocr*.md", "board_ocr*.json", "benchmark.md"):
            for fp in note_src.glob(pattern):
                dst = odest / fp.name
                if not dst.exists():
                    shutil.move(str(fp), str(dst))
                moved.append(str(dst))
        if (odest / "board_ocr_1080p_full.json").is_file():
            fix_ocr_json_paths(odest / "board_ocr_1080p_full.json")

    latex = skill_latex_dir(video_id)
    if latex.is_dir():
        cdest = board_crops_dir(video_id)
        cdest.mkdir(parents=True, exist_ok=True)
        for fp in latex.glob("*_crop.jpg"):
            dst = cdest / fp.name
            if not dst.exists():
                shutil.move(str(fp), str(dst))
            moved.append(str(dst))
        for fp in latex.glob("*.svg"):
            fp.unlink()

    leftover = OLD_PILOT / video_id
    if leftover.exists() and not any(leftover.rglob("*")):
        shutil.rmtree(leftover, ignore_errors=True)
    if OLD_PILOT.exists() and not any(OLD_PILOT.iterdir()):
        OLD_PILOT.rmdir()

    return moved


def main() -> int:
    YOUTUBE_PROCESS_ROOT.mkdir(parents=True, exist_ok=True)
    video_ids = []
    if OLD_PILOT.exists():
        video_ids.extend(p.name for p in OLD_PILOT.iterdir() if p.is_dir())
    if OLD_NOTES.exists():
        for p in OLD_NOTES.iterdir():
            if p.is_dir() and p.name not in video_ids:
                video_ids.append(p.name)

    all_moved: list[str] = []
    for vid in sorted(video_ids):
        all_moved.extend(migrate_video(vid))
        print(f"Migrated {vid}: {len(all_moved)} paths touched")

    print(f"YouTubeProcess root: {YOUTUBE_PROCESS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
