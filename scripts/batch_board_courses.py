#!/usr/bin/env python3
"""Batch board OCR + Whisper segments for Fourier optics & RF microwave courses."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from process_lesson import is_lesson_complete, run_one  # noqa: E402
from youtube_process_paths import (  # noqa: E402
    YOUTUBE_SKILL_DIR,
    lesson_sort_key,
    manifest_by_id,
    manifest_video,
    skill_board_index_path,
)

PY = Path(r"C:\ProgramData\anaconda3\python.exe")
DEFAULT_LOG = YOUTUBE_SKILL_DIR / "fo_rf_process_progress.log"
BUILD_LITE = SCRIPTS / "build_course_lite.py"
BUILD_FULL = SCRIPTS / "build_course_full.py"
BUILD_INDEX = SCRIPTS / "build_youtube_process_index.py"
SEGMENT_ALL = SCRIPTS / "segment_from_transcript.py"

DEFAULT_COURSES = ["fourier_optics", "rf_microwave"]


def log_line(log_path: Path, msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def collect_ids(courses: list[str], *, only_remaining: bool) -> list[str]:
    ids: list[str] = []
    for course in courses:
        entries = [v for v in manifest_by_id().values() if v.get("course") == course]
        entries.sort(key=lambda v: lesson_sort_key(v.get("title") or "", course))
        for v in entries:
            vid = v["id"]
            if only_remaining and is_lesson_complete(vid):
                continue
            ids.append(vid)
    return ids


def board_scene_count(video_id: str) -> int:
    path = skill_board_index_path(video_id)
    if not path.is_file():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return len(data.get("scenes") or [])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch board+segments for FO & RF courses")
    parser.add_argument(
        "--course",
        action="append",
        dest="courses",
        choices=DEFAULT_COURSES,
        help="Course id (repeatable; default: both FO and RF)",
    )
    parser.add_argument("--only-remaining", action="store_true", help="Skip lessons already complete")
    parser.add_argument("--progress-log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-segments", action="store_true")
    parser.add_argument("--skip-latex", action="store_true")
    parser.add_argument("--skip-correct", action="store_true")
    parser.add_argument("--pix2tex", action="store_true")
    parser.add_argument("--whisper-model", default="tiny")
    parser.add_argument("--finalize", action="store_true", help="Rebuild Course Lite + Full when done")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    courses = args.courses or list(DEFAULT_COURSES)
    log_path = args.progress_log.resolve()

    log_line(log_path, f"SESSION START courses={courses} finalize={args.finalize}")

    ids = collect_ids(courses, only_remaining=args.only_remaining)
    by_course: dict[str, int] = {}
    for vid in ids:
        c = manifest_video(vid).get("course") or "?"
        by_course[c] = by_course.get(c, 0) + 1
    log_line(
        log_path,
        f"PLAN total={len(ids)} by_course={by_course} only_remaining={args.only_remaining}",
    )

    if args.dry_run:
        for i, vid in enumerate(ids, 1):
            v = manifest_video(vid)
            log_line(log_path, f"DRY [{i}/{len(ids)}] {vid} | {v.get('course')} | {v.get('title')}")
        return 0

    if not ids:
        log_line(log_path, "DONE ok=0 fail=0 (nothing to process)")
        return 0

    ok = 0
    fail = 0
    failed_ids: list[str] = []
    t_session = time.time()

    for i, vid in enumerate(ids, 1):
        v = manifest_video(vid)
        title = v.get("title") or vid
        course = v.get("course") or "?"
        log_line(log_path, f"START [{i}/{len(ids)}] {vid} | {course} | {title}")
        t0 = time.time()
        try:
            run_one(
                vid,
                skip_ocr=args.skip_ocr,
                skip_segments=args.skip_segments,
                skip_latex=args.skip_latex,
                skip_correct=args.skip_correct,
                no_pix2tex=not args.pix2tex,
                whisper_model=args.whisper_model,
                log_path=log_path,
            )
            scenes = board_scene_count(vid)
            elapsed = time.time() - t0
            log_line(
                log_path,
                f"OK [{i}/{len(ids)}] {vid} | scenes={scenes} | elapsed={elapsed:.0f}s",
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - t0
            log_line(
                log_path,
                f"FAIL [{i}/{len(ids)}] {vid} | elapsed={elapsed:.0f}s | {exc}",
            )
            fail += 1
            failed_ids.append(vid)

        avg = (time.time() - t_session) / i
        eta_min = avg * (len(ids) - i) / 60
        pct = 100.0 * i / len(ids)
        log_line(
            log_path,
            f"PROGRESS done={i}/{len(ids)} ({pct:.1f}%) ok={ok} fail={fail} eta={eta_min:.0f}min",
        )

    subprocess.run([str(PY), str(BUILD_INDEX)], check=False)
    log_line(log_path, "INDEX rebuilt YouTubeProcess")

    if args.finalize:
        log_line(log_path, "FINALIZE segment_from_transcript --all")
        subprocess.run([str(PY), str(SEGMENT_ALL), "--all"], check=False)
        log_line(log_path, "FINALIZE build_course_lite")
        subprocess.run([str(PY), str(BUILD_LITE)], check=True)
        log_line(log_path, "FINALIZE build_course_full --all-with-board")
        subprocess.run([str(PY), str(BUILD_FULL), "--all-with-board"], check=True)
        log_line(log_path, "FINALIZE complete")

    total_min = (time.time() - t_session) / 60
    log_line(log_path, f"DONE ok={ok} fail={fail} elapsed={total_min:.1f}min")
    if failed_ids:
        log_line(log_path, f"FAILED_IDS {','.join(failed_ids)}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
