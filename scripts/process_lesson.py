#!/usr/bin/env python3
"""Full lesson pipeline: download 1080p, board OCR, LaTeX gate, whisper segments, glossary fix."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PY = Path(r"C:\ProgramData\anaconda3\python.exe")
EXTRACT = SCRIPTS / "extract_board_frames.py"
BACKFILL = SCRIPTS / "backfill_segments.py"
BUILD = SCRIPTS / "build_youtube_process_index.py"
BOARD_TO_LATEX = SCRIPTS / "board_to_latex.py"
CORRECT = SCRIPTS / "correct_transcript.py"

from transcript_utils import find_skill_segments
from youtube_process_paths import (
    board_work_dir,
    lesson_sort_key,
    manifest_by_id,
    skill_board_index_path,
    video_path,
)


def is_lesson_complete(video_id: str) -> bool:
    board = board_work_dir(video_id, 1080)
    n_frames = len(list((board / "frames").glob("*.jpg"))) if (board / "frames").is_dir() else 0
    return (
        video_path(video_id).is_file()
        and bool(find_skill_segments(video_id))
        and n_frames > 0
        and skill_board_index_path(video_id).is_file()
    )


def em_video_ids(*, only_remaining: bool = False) -> list[str]:
    entries = [v for v in manifest_by_id().values() if v.get("course") == "em"]
    entries.sort(key=lambda v: lesson_sort_key(v.get("title") or "", "em"))
    ids = [v["id"] for v in entries]
    if only_remaining:
        ids = [vid for vid in ids if not is_lesson_complete(vid)]
    return ids


def vid_arg(video_id: str) -> str:
    """argparse-safe --video-id=VALUE (IDs may start with '-')."""
    return f"--video-id={video_id}"


def run_one(
    video_id: str,
    *,
    skip_ocr: bool = False,
    skip_segments: bool = False,
    skip_latex: bool = False,
    skip_correct: bool = False,
    no_pix2tex: bool = True,
    whisper_model: str = "tiny",
    rebuild_index: bool = False,
    log_path: Path | None = None,
) -> None:
    print(f"\n========== {video_id} ==========", flush=True)

    def run_cmd(cmd: list[str]) -> None:
        if log_path:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n--- $ {' '.join(cmd)} ---\n")
                f.flush()
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True)
        else:
            subprocess.run(cmd, check=True)

    if not skip_ocr:
        run_cmd([str(PY), str(EXTRACT), vid_arg(video_id), "--full", "--height", "1080"])
    if not skip_latex:
        latex_cmd = [str(PY), str(BOARD_TO_LATEX), vid_arg(video_id), "--all"]
        if no_pix2tex:
            latex_cmd.append("--no-pix2tex")
        run_cmd(latex_cmd)
    if not skip_segments:
        run_cmd(
            [str(PY), str(BACKFILL), vid_arg(video_id), "--force", "--model", whisper_model],
        )
    if not skip_correct:
        run_cmd([str(PY), str(CORRECT), vid_arg(video_id)])
    if rebuild_index:
        subprocess.run([str(PY), str(BUILD)], check=False)


def course_video_ids(course: str, *, only_remaining: bool = False) -> list[str]:
    entries = [v for v in manifest_by_id().values() if v.get("course") == course]
    entries.sort(key=lambda v: lesson_sort_key(v.get("title") or "", course))
    ids = [v["id"] for v in entries]
    if only_remaining:
        ids = [vid for vid in ids if not is_lesson_complete(vid)]
    return ids


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", action="append", dest="video_ids")
    parser.add_argument("--em-all", action="store_true", help="all EM lectures in numeric order")
    parser.add_argument("--em-remaining", action="store_true", help="EM lectures not yet fully processed")
    parser.add_argument(
        "--course",
        action="append",
        dest="courses",
        help="all lectures in course (e.g. fourier_optics, rf_microwave)",
    )
    parser.add_argument("--only-remaining", action="store_true", help="with --course, skip completed lessons")
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--skip-segments", action="store_true")
    parser.add_argument("--skip-latex", action="store_true")
    parser.add_argument("--skip-correct", action="store_true")
    parser.add_argument("--pix2tex", action="store_true", help="enable pix2tex (slow)")
    parser.add_argument("--whisper-model", default="tiny")
    parser.add_argument("--rebuild-index", action="store_true", help="rebuild index after each lesson")
    parser.add_argument("--rebuild-index-once", action="store_true", help="rebuild index after last lesson")
    args = parser.parse_args()

    ids = list(args.video_ids or [])
    if args.em_all:
        ids.extend(em_video_ids(only_remaining=False))
    elif args.em_remaining:
        ids.extend(em_video_ids(only_remaining=True))
    for course in args.courses or []:
        ids.extend(course_video_ids(course, only_remaining=args.only_remaining))

    ids = list(dict.fromkeys(ids))
    if not ids:
        print("No video ids (use --video-id, --em-all, --em-remaining, or --course)")
        return 1

    print(f"Processing {len(ids)} lesson(s)...")
    failed: list[str] = []
    for i, vid in enumerate(ids):
        try:
            run_one(
                vid,
                skip_ocr=args.skip_ocr,
                skip_segments=args.skip_segments,
                skip_latex=args.skip_latex,
                skip_correct=args.skip_correct,
                no_pix2tex=not args.pix2tex,
                whisper_model=args.whisper_model,
                rebuild_index=args.rebuild_index,
            )
        except subprocess.CalledProcessError as exc:
            print(f"FAILED {vid}: {exc}", flush=True)
            failed.append(vid)

    if args.rebuild_index_once or args.em_all or args.em_remaining or args.courses:
        subprocess.run([str(PY), str(BUILD)], check=False)
        print("Rebuilt YouTubeProcess index.")

    if failed:
        print(f"Failed lessons ({len(failed)}): {', '.join(failed)}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
