#!/usr/bin/env python3
"""Fetch YouTube channel metadata and transcripts for 鄭宇翔 teaching videos.

Priority:
1. YouTube captions (manual or auto) via youtube-transcript-api
2. ASR fallback via faster-whisper on downloaded audio (yt-dlp)

Usage:
  python crawl_youtube_transcripts.py --list-only
  python crawl_youtube_transcripts.py --all                    # 全部未完成的影片（斷點續跑）
  python crawl_youtube_transcripts.py --course em --max 5
  python crawl_youtube_transcripts.py --video-id nocZR2m180M

Live dashboard (separate terminal):
  python watch_youtube_crawl.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

CHANNEL_URL = "https://www.youtube.com/channel/UCkVcI3rBHx2t49mdCsHLG4w/videos"
YTDLP = r"C:\ProgramData\anaconda3\Scripts\yt-dlp.exe"
FFMPEG = Path(r"C:\ProgramData\anaconda3\Library\bin\ffmpeg.exe")
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from transcript_utils import (
    SEGMENT_SYNC_CAPTION,
    SEGMENT_SYNC_WHISPER,
    save_segments_json,
    segments_from_whisper,
    sync_transcript_to_lesson,
)
OUT_DIR = ROOT / "references" / "sources" / "youtube"
MANIFEST_PATH = OUT_DIR / "manifest.json"
TRANSCRIPTS_DIR = OUT_DIR / "transcripts"
PROGRESS_LOG = OUT_DIR / "crawl_progress.log"
MAX_RETRIES = 3
RETRY_DELAY_SEC = 10.0

COURSE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fourier_optics_lab", re.compile(r"傅氏光學實驗")),
    (
        "fourier_optics",
        re.compile(
            r"傅立葉|傅氏轉換與傅氏光學|Fourier transform and Fourier optics|Fresnel|Fraunhofer|Holography|diffraction|Angular spectrum",
            re.I,
        ),
    ),
    ("em", re.compile(r"電磁學一|Electromagnetics", re.I)),
    ("rf_microwave", re.compile(r"射頻|RF and microwave|微波系統|Bandpass|Butterworth|PLL|Receiver|HFSS|Chebyshev|Bessel", re.I)),
    ("radio_life", re.compile(r"生活中的電波|Radio waves in our life", re.I)),
    ("podcast", re.compile(r"未來雜貨電|EP8[567]", re.I)),
    ("demo", re.compile(r"PLUTO|SDR|demo", re.I)),
]

COURSE_PRIORITY = [
    "em",
    "fourier_optics",
    "fourier_optics_lab",
    "rf_microwave",
    "radio_life",
    "podcast",
    "demo",
    "other",
]

_WHISPER_MODEL: Any = None
_WHISPER_MODEL_KEY: str | None = None


@dataclass
class VideoEntry:
    id: str
    title: str
    duration: float | None
    url: str
    course: str
    transcript_source: str | None = None
    transcript_path: str | None = None
    word_count: int | None = None
    error: str | None = None


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with PROGRESS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_ytdlp_json(url: str) -> dict[str, Any]:
    proc = subprocess.run(
        [YTDLP, "-J", "--flat-playlist", url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "yt-dlp failed")
    return json.loads(proc.stdout)


def classify_course(title: str) -> str:
    for name, pattern in COURSE_PATTERNS:
        if pattern.search(title):
            return name
    return "other"


def lecture_number(title: str) -> int | None:
    for pat in (r"電磁學一\s*(\d+)", r"微波系統導論\s*(\d+)", r"傅[立氏]葉.*?(\d+)", r"傅氏轉換與傅氏光學\s*(\d+)"):
        m = re.search(pat, title)
        if m:
            return int(m.group(1))
    return None


def extract_entries(playlist: dict[str, Any]) -> list[VideoEntry]:
    entries: list[VideoEntry] = []
    for item in playlist.get("entries") or []:
        if not item:
            continue
        vid = item.get("id")
        title = item.get("title") or ""
        if not vid:
            continue
        entries.append(
            VideoEntry(
                id=vid,
                title=title,
                duration=item.get("duration"),
                url=f"https://www.youtube.com/watch?v={vid}",
                course=classify_course(title),
            )
        )
    return entries


def sort_for_crawl(entries: list[VideoEntry]) -> list[VideoEntry]:
    def key(e: VideoEntry) -> tuple:
        try:
            prio = COURSE_PRIORITY.index(e.course)
        except ValueError:
            prio = 99
        return (prio, lecture_number(e.title) or 999, e.duration or 10**9, e.title)

    return sorted(entries, key=key)


def try_youtube_captions(video_id: str) -> tuple[str, str, list[dict]] | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None

    api = YouTubeTranscriptApi()
    for langs in (["zh-Hant", "zh-Hans", "zh-TW", "zh-CN", "en"], ["en"]):
        try:
            fetched = api.fetch(video_id, languages=langs)
            segments: list[dict] = []
            for seg in fetched:
                text = seg.text.strip()
                if not text:
                    continue
                start = float(seg.start)
                end = start + float(seg.duration)
                segments.append({"start": round(start, 2), "end": round(end, 2), "text": text})
            text = " ".join(s["text"] for s in segments)
            if text:
                return text, "youtube_caption", segments
        except Exception:
            continue
    return None


def get_whisper_model(model_size: str, backend: str) -> Any:
    global _WHISPER_MODEL, _WHISPER_MODEL_KEY
    key = f"{backend}:{model_size}"
    if _WHISPER_MODEL is not None and _WHISPER_MODEL_KEY == key:
        return _WHISPER_MODEL
    if backend == "faster" or backend == "auto":
        from faster_whisper import WhisperModel

        _WHISPER_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
    else:
        import whisper

        _WHISPER_MODEL = whisper.load_model(model_size)
    _WHISPER_MODEL_KEY = key
    return _WHISPER_MODEL


def transcribe_audio(audio_path: Path, model_size: str, backend: str) -> tuple[str, list[dict]]:
    errors: list[str] = []
    backends = [backend] if backend != "auto" else ["faster", "openai"]
    for name in backends:
        try:
            model = get_whisper_model(model_size, name)
            if name == "faster":
                raw_segments, _info = model.transcribe(
                    str(audio_path),
                    language="zh",
                    vad_filter=True,
                    beam_size=5,
                )
                segments = segments_from_whisper(raw_segments)
                text = " ".join(s["text"] for s in segments)
            else:
                result = model.transcribe(str(audio_path), language="zh", verbose=False)
                text = (result.get("text") or "").strip()
                segments = [
                    {
                        "start": round(float(s["start"]), 2),
                        "end": round(float(s["end"]), 2),
                        "text": str(s["text"]).strip(),
                    }
                    for s in result.get("segments") or []
                    if str(s.get("text", "")).strip()
                ]
            if text:
                return text, segments
            errors.append(f"{name}: empty transcript")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors))


def download_audio(video_id: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    out_template = str(dest) + ".%(ext)s"
    cmd = [
        YTDLP,
        "-f",
        "18/bestaudio/best",
        "--extractor-args",
        "youtube:player_client=android",
        "-o",
        out_template,
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    if FFMPEG.is_file():
        cmd.insert(1, "--ffmpeg-location")
        cmd.insert(2, str(FFMPEG.parent))
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "audio download failed")

    candidates = sorted(dest.parent.glob(f"{dest.name}.*"))
    if not candidates:
        bare = dest.parent / dest.name
        if bare.is_file():
            return bare
        raise RuntimeError("audio file not found after download")
    return candidates[0]


def fetch_transcript(video_id: str, whisper_model: str, whisper_backend: str) -> tuple[str, str, list[dict]]:
    caption = try_youtube_captions(video_id)
    if caption:
        return caption

    with tempfile.TemporaryDirectory() as tmp:
        audio_base = Path(tmp) / video_id
        audio_path = download_audio(video_id, audio_base)
        text, segments = transcribe_audio(audio_path, model_size=whisper_model, backend=whisper_backend)
        if not text:
            raise RuntimeError("empty ASR transcript")
        source = "faster_whisper_asr"
        if whisper_backend == "openai":
            source = "openai_whisper_asr"
        elif whisper_backend == "auto":
            source = "whisper_asr"
        return text, source, segments


def save_transcript(
    video_id: str,
    title: str,
    course: str,
    text: str,
    source: str,
    segments: list[dict] | None = None,
) -> Path:
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r'[<>:"/\\|?*]+', "_", title)[:80]
    path = TRANSCRIPTS_DIR / f"{video_id}_{course}_{safe_title}.txt"
    header = (
        f"# {title}\n"
        f"# video_id: {video_id}\n"
        f"# course: {course}\n"
        f"# source: {source}\n"
        f"# fetched_at: {datetime.now(timezone.utc).isoformat()}\n\n"
    )
    path.write_text(header + text + "\n", encoding="utf-8")
    if segments:
        if source == "youtube_caption":
            sync_source = SEGMENT_SYNC_CAPTION
        else:
            sync_source = SEGMENT_SYNC_WHISPER
        save_segments_json(path, segments, sync_source=sync_source)
    return path


def transcript_exists(video_id: str) -> bool:
    if not TRANSCRIPTS_DIR.exists():
        return False
    return any(TRANSCRIPTS_DIR.glob(f"{video_id}_*.txt")) or (TRANSCRIPTS_DIR / f"{video_id}.txt").is_file()


def pick_sample(entries: list[VideoEntry], n: int) -> list[VideoEntry]:
    buckets: dict[str, list[VideoEntry]] = {}
    for e in entries:
        buckets.setdefault(e.course, []).append(e)

    picked: list[VideoEntry] = []
    for course in COURSE_PRIORITY:
        items = sorted(buckets.get(course, []), key=lambda x: x.duration or 10**9)
        if items:
            picked.append(items[0])

    if len(picked) < n:
        seen = {p.id for p in picked}
        rest = sorted(
            [e for e in entries if e.id not in seen],
            key=lambda x: x.duration or 10**9,
        )
        picked.extend(rest[: n - len(picked)])
    return picked[:n]


def load_manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"channel_url": CHANNEL_URL, "videos": []}


def save_manifest(data: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_manifest_entry(entry: VideoEntry) -> None:
    data = load_manifest()
    by_id = {v["id"]: v for v in data.get("videos", [])}
    by_id[entry.id] = {**by_id.get(entry.id, {}), **asdict(entry)}
    data["videos"] = sorted(by_id.values(), key=lambda v: v.get("title", ""))
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["channel_url"] = CHANNEL_URL
    stats = {
        "total_videos": len(data["videos"]),
        "with_transcript": sum(1 for v in data["videos"] if v.get("transcript_path")),
        "with_error": sum(1 for v in data["videos"] if v.get("error")),
    }
    data["transcript_stats"] = stats
    save_manifest(data)


def merge_manifest_all(entries: list[VideoEntry]) -> None:
    data = load_manifest()
    by_id = {v["id"]: v for v in data.get("videos", [])}
    for e in entries:
        e.course = classify_course(e.title)
        by_id[e.id] = {**by_id.get(e.id, {}), **asdict(e)}
    data["videos"] = sorted(by_id.values(), key=lambda v: v.get("title", ""))
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["channel_url"] = CHANNEL_URL
    save_manifest(data)


def is_done(entry: VideoEntry, force: bool) -> bool:
    if force:
        return False
    if transcript_exists(entry.id):
        return True
    data = load_manifest()
    for v in data.get("videos", []):
        if v.get("id") == entry.id and v.get("transcript_path"):
            rel = ROOT / v["transcript_path"]
            if rel.is_file():
                return True
    return False


def process_one(entry: VideoEntry, whisper_model: str, whisper_backend: str) -> VideoEntry:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            text, source, segments = fetch_transcript(entry.id, whisper_model, whisper_backend)
            path = save_transcript(entry.id, entry.title, entry.course, text, source, segments)
            entry.transcript_source = source
            entry.transcript_path = str(path.relative_to(ROOT))
            entry.word_count = len(text)
            entry.error = None
            merge_manifest_entry(entry)
            sync_transcript_to_lesson(entry.id, entry.duration)
            log(f"OK {entry.id} | {entry.course} | {entry.title} | {entry.word_count} chars")
            return entry
        except Exception as exc:  # noqa: BLE001
            entry.error = str(exc)[:500]
            log(f"RETRY {attempt}/{MAX_RETRIES} {entry.id}: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC * attempt)
            else:
                merge_manifest_entry(entry)
                log(f"FAIL {entry.id} | {entry.title} | {exc}")
    return entry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("--all", action="store_true", help="transcribe all videos (resume skips done)")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--course", choices=[c for c, _ in COURSE_PATTERNS] + ["other"])
    parser.add_argument("--max", type=int, default=0)
    parser.add_argument("--video-id")
    parser.add_argument("--whisper-model", default="tiny")
    parser.add_argument("--whisper-backend", choices=["auto", "faster", "openai"], default="faster")
    parser.add_argument("--em-lectures-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    log("Fetching channel metadata...")
    playlist = run_ytdlp_json(CHANNEL_URL)
    entries = extract_entries(playlist)
    log(f"Found {len(entries)} videos")

    if args.list_only:
        merge_manifest_all(entries)
        summary: dict[str, int] = {}
        for e in entries:
            summary[e.course] = summary.get(e.course, 0) + 1
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    targets: list[VideoEntry] = []
    if args.all:
        targets = sort_for_crawl(entries)
    elif args.video_id:
        targets = [e for e in entries if e.id == args.video_id]
        if not targets:
            log(f"Video id not found: {args.video_id}")
            return 1
    elif args.sample:
        targets = pick_sample(entries, args.sample)
    elif args.course:
        targets = [e for e in entries if e.course == args.course]
        if args.em_lectures_only:
            targets = [e for e in targets if re.search(r"電磁學一\s*\d+", e.title)]
        targets = sort_for_crawl(targets)
        if args.max:
            targets = targets[: args.max]
    else:
        parser.error("Specify --list-only, --all, --sample, --course, or --video-id")

    pending = [e for e in targets if not is_done(e, args.force)]
    log(f"Targets: {len(targets)}, pending: {len(pending)}")

    ok = err = skip = 0
    for entry in targets:
        if is_done(entry, args.force):
            skip += 1
            log(f"SKIP {entry.id} | {entry.title}")
            continue
        log(f"START {entry.id} | {entry.course} | {entry.title}")
        process_one(entry, args.whisper_model, args.whisper_backend)
        if entry.transcript_path:
            ok += 1
        else:
            err += 1

    merge_manifest_all(entries)
    try:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "sync_manifest_transcripts.py"), "--rebuild-index"],
            check=False,
            cwd=str(ROOT),
        )
        log("Synced manifest transcript_path + teaching_index.json")
    except Exception as exc:  # noqa: BLE001
        log(f"manifest sync skipped: {exc}")
    log(f"DONE ok={ok} err={err} skip={skip} manifest={MANIFEST_PATH}")

    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
