"""Transcript parsing, segments, and sync to YouTubeProcess."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from youtube_process_paths import (
    SKILL_ROOT,
    TRANSCRIPTS_DIR,
    lesson_dir,
    lesson_transcript_dir,
    manifest_by_id,
)


def find_skill_transcript(video_id: str) -> Path | None:
    entry = manifest_by_id().get(video_id)
    if entry and entry.get("transcript_path"):
        p = SKILL_ROOT / Path(str(entry["transcript_path"]).replace("\\", "/"))
        if p.is_file():
            return p
    if TRANSCRIPTS_DIR.exists():
        matches = sorted(TRANSCRIPTS_DIR.glob(f"{video_id}_*.txt"))
        if matches:
            return matches[0]
        legacy = TRANSCRIPTS_DIR / f"{video_id}.txt"
        if legacy.is_file():
            return legacy
    return None


SEGMENT_SYNC_WHISPER = "whisper"
SEGMENT_SYNC_CAPTION = "youtube_caption"
SEGMENT_SYNC_TEXT = "text_proportional"
REALTIME_SEGMENT_SOURCES = {SEGMENT_SYNC_WHISPER, SEGMENT_SYNC_CAPTION}


def segments_meta_path(txt_path: Path) -> Path:
    return txt_path.with_suffix(".segments.meta.json")


def infer_segment_sync_source(segments: list[dict]) -> str:
    """Best-effort guess for legacy segments.json without meta."""
    if not segments:
        return SEGMENT_SYNC_TEXT
    if len(segments) < 20:
        return SEGMENT_SYNC_TEXT
    sample = segments[:40]
    avg_dur = sum(s["end"] - s["start"] for s in sample) / len(sample)
    irregular = sum(1 for s in sample if abs(s["start"] - round(s["start"])) > 0.05)
    if irregular >= 5 and avg_dur < 12:
        return SEGMENT_SYNC_WHISPER
    return SEGMENT_SYNC_TEXT


def load_segment_sync_source(video_id: str) -> str | None:
    txt = find_skill_transcript(video_id)
    if not txt or not find_skill_segments(video_id):
        return None
    meta_path = segments_meta_path(txt)
    if meta_path.is_file():
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data.get("sync_source") or data.get("source")
    segments = json.loads(find_skill_segments(video_id).read_text(encoding="utf-8"))
    return infer_segment_sync_source(segments)


def segment_sync_is_realtime(video_id: str) -> bool:
    src = load_segment_sync_source(video_id)
    return src in REALTIME_SEGMENT_SOURCES if src else False


def find_skill_segments(video_id: str) -> Path | None:
    txt = find_skill_transcript(video_id)
    if not txt:
        return None
    seg = txt.with_suffix(".segments.json")
    return seg if seg.is_file() else None


def parse_transcript_header(text: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False
    for line in text.splitlines():
        if not in_body and line.startswith("# "):
            key = line[2:].split(":", 1)
            if len(key) == 2:
                meta[key[0].strip()] = key[1].strip()
            elif not meta.get("title"):
                meta["title"] = line[2:].strip()
            continue
        if not in_body and line.strip() == "":
            in_body = True
            continue
        if in_body:
            body_lines.append(line)
    return meta, "\n".join(body_lines).strip()


def segments_from_whisper(
    segments_iter,
) -> list[dict]:
    out: list[dict] = []
    for seg in segments_iter:
        text = (getattr(seg, "text", None) or seg.get("text", "")).strip()
        if not text:
            continue
        start = float(getattr(seg, "start", None) if not isinstance(seg, dict) else seg["start"])
        end = float(getattr(seg, "end", None) if not isinstance(seg, dict) else seg["end"])
        out.append({"start": round(start, 2), "end": round(end, 2), "text": text})
    return out


def _split_transcript_chunks(body: str, target_chars: int = 36, max_chars: int = 52) -> list[str]:
    """Split transcript body into subtitle-sized chunks without re-downloading audio."""
    text = re.sub(r"\s+", " ", body.replace("\n", " ")).strip()
    if not text:
        return []

    punct_parts = [p.strip() for p in re.split(r"(?<=[。！？!?；;])\s*", text) if p.strip()]
    if len(punct_parts) >= 4:
        chunks: list[str] = []
        buf: list[str] = []
        size = 0
        for part in punct_parts:
            part_len = len(part)
            if buf and size + part_len > max_chars:
                chunks.append("".join(buf))
                buf = [part]
                size = part_len
            else:
                buf.append(part)
                size += part_len
        if buf:
            chunks.append("".join(buf))
        return chunks

    words = [w for w in re.split(r"\s+", text) if w]
    if len(words) >= 2:
        chunks = []
        buf = []
        size = 0
        for word in words:
            add = len(word) + (1 if buf else 0)
            if buf and size + add > max_chars:
                chunks.append(" ".join(buf))
                buf = [word]
                size = len(word)
            else:
                buf.append(word)
                size += add
        if buf:
            chunks.append(" ".join(buf))
        if len(chunks) >= 2:
            return chunks

    return [text[i : i + target_chars] for i in range(0, len(text), target_chars)]


def segments_from_plain_text(body: str, duration_sec: float | None) -> list[dict]:
    """Assign proportional timestamps to existing transcript text (no ASR re-run)."""
    chunks = _split_transcript_chunks(body)
    if not chunks:
        return []

    dur = float(duration_sec or max(len(body) / 4.0, 60))
    total_chars = sum(len(c) for c in chunks) or 1
    segments: list[dict] = []
    t = 0.0
    for chunk in chunks:
        seg_dur = dur * (len(chunk) / total_chars)
        end = min(t + seg_dur, dur)
        segments.append({"start": round(t, 2), "end": round(end, 2), "text": chunk})
        t = end
    if segments:
        segments[-1]["end"] = round(dur, 2)
    return segments


def load_segments(video_id: str, duration_sec: float | None = None) -> list[dict]:
    seg_path = find_skill_segments(video_id)
    if seg_path:
        return json.loads(seg_path.read_text(encoding="utf-8"))
    txt = find_skill_transcript(video_id)
    if not txt:
        return []
    _, body = parse_transcript_header(txt.read_text(encoding="utf-8"))
    return segments_from_plain_text(body, duration_sec)


def save_segments_json(
    txt_path: Path,
    segments: list[dict],
    sync_source: str = SEGMENT_SYNC_TEXT,
) -> Path:
    out = txt_path.with_suffix(".segments.json")
    out.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = segments_meta_path(txt_path)
    meta.write_text(
        json.dumps({"sync_source": sync_source}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def sync_transcript_to_lesson(video_id: str, duration_sec: float | None = None) -> Path | None:
    src = find_skill_transcript(video_id)
    if not src:
        return None
    dest_dir = lesson_transcript_dir(video_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / "transcript.txt")
    segments = load_segments(video_id, duration_sec)
    if segments:
        (dest_dir / "segments.json").write_text(
            json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        meta_src = segments_meta_path(src)
        if meta_src.is_file():
            shutil.copy2(meta_src, dest_dir / "segments.meta.json")
    return dest_dir


def sync_all_transcripts() -> int:
    count = 0
    for vid, entry in manifest_by_id().items():
        if not entry.get("transcript_path") and not find_skill_transcript(vid):
            continue
        ld = lesson_dir(vid)
        ld.mkdir(parents=True, exist_ok=True)
        if sync_transcript_to_lesson(vid, entry.get("duration")):
            count += 1
    return count
