#!/usr/bin/env python3
"""Backfill Whisper segments for videos that only have plain-text transcripts."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from transcript_utils import (
    SEGMENT_SYNC_WHISPER,
    find_skill_segments,
    find_skill_transcript,
    save_segments_json,
    segments_from_whisper,
    sync_transcript_to_lesson,
)
from youtube_process_paths import manifest_by_id, video_path

FFMPEG = Path(r"C:\ProgramData\anaconda3\Library\bin\ffmpeg.exe")


def extract_audio(mp4: Path, wav: Path) -> None:
    cmd = [
        str(FFMPEG),
        "-y",
        "-i",
        str(mp4),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(wav),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "ffmpeg failed")


def transcribe(video_id: str, model_size: str) -> list[dict]:
    mp4 = video_path(video_id)
    if not mp4.is_file():
        raise FileNotFoundError(f"Missing local video: {mp4}")

    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / f"{video_id}.wav"
        print(f"Extracting audio from {mp4.name}...")
        extract_audio(mp4, wav)
        print(f"Transcribing with faster-whisper ({model_size})...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        raw, _info = model.transcribe(str(wav), language="zh", vad_filter=True, beam_size=5)
        return segments_from_whisper(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    vid = args.video_id
    if find_skill_segments(vid) and not args.force:
        print(f"Segments already exist for {vid}; use --force to regenerate.")
        return 0

    txt = find_skill_transcript(vid)
    if not txt:
        print(f"No transcript found for {vid}")
        return 1

    segments = transcribe(vid, args.model)
    out = save_segments_json(txt, segments, sync_source=SEGMENT_SYNC_WHISPER)
    entry = manifest_by_id().get(vid, {})
    sync_transcript_to_lesson(vid, entry.get("duration"))
    print(f"Wrote {len(segments)} segments -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
