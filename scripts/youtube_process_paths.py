"""Shared paths: Skill vs YouTubeProcess (courses / lesson folders)."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SKILL_ROOT.parent.parent.parent
YOUTUBE_PROCESS_ROOT = Path(
    os.environ.get("YOUTUBE_PROCESS_ROOT", WORKSPACE_ROOT / "YouTubeProcess")
)
PIX2TEX_VENV = Path(
    os.environ.get("PIX2TEX_VENV", YOUTUBE_PROCESS_ROOT / ".venv-pix2tex")
)

YOUTUBE_SKILL_DIR = SKILL_ROOT / "references" / "sources" / "youtube"
MANIFEST_PATH = YOUTUBE_SKILL_DIR / "manifest.json"
BOARD_NOTES_DIR = YOUTUBE_SKILL_DIR / "board_notes"
TRANSCRIPTS_DIR = YOUTUBE_SKILL_DIR / "transcripts"

COURSE_LABELS: dict[str, str] = {
    "em": "電磁學一",
    "fourier_optics": "傅立葉光學",
    "fourier_optics_lab": "傅氏光學實驗",
    "rf_microwave": "微波系統導論",
    "radio_life": "生活中的電波",
    "podcast": "未來雜貨電",
    "demo": "實驗 Demo",
    "other": "其他",
}

COURSE_ORDER = [
    "em",
    "fourier_optics",
    "fourier_optics_lab",
    "rf_microwave",
    "radio_life",
    "podcast",
    "demo",
    "other",
]


def lesson_sort_key(title: str, course: str = "") -> tuple:
    """Natural numeric order for numbered lecture series (avoids 10 before 2)."""
    series_patterns: list[tuple[str, object]] = [
        (r"電磁學一\s*(\d+)", lambda m: (0, int(m.group(1)), 0, 0)),
        (r"微波系統導論\s*(\d+)", lambda m: (0, int(m.group(1)), 0, 0)),
        (r"傅氏轉換與傅氏光學\s*(\d+)", lambda m: (0, int(m.group(1)), 0, 0)),
        (r"傅氏光學實驗(\d+)(?:-(\d+))?", lambda m: (0, int(m.group(1)), int(m.group(2) or 0), 0)),
        (r"生活中的電波\(?(\d+)\)?", lambda m: (0, int(m.group(1)), 0, 0)),
    ]
    for pat, key_fn in series_patterns:
        m = re.search(pat, title)
        if m:
            return key_fn(m) + (title,)
    return (1, 0, 0, 0, title)


def safe_dir_name(name: str, max_len: int = 120) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\n\r\t]+', "_", name).strip()
    return (cleaned[:max_len].rstrip(". ") if cleaned else "untitled")


@lru_cache(maxsize=1)
def manifest_by_id() -> dict[str, dict]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {v["id"]: v for v in data.get("videos") or []}


def manifest_video(video_id: str) -> dict:
    entry = manifest_by_id().get(video_id)
    if not entry:
        raise KeyError(f"video_id not in manifest: {video_id}")
    return entry


def lesson_dir(video_id: str) -> Path:
    v = manifest_video(video_id)
    return YOUTUBE_PROCESS_ROOT / "courses" / v["course"] / safe_dir_name(v["title"])


def lesson_meta_path(video_id: str) -> Path:
    return lesson_dir(video_id) / "meta.json"


def write_lesson_meta(video_id: str) -> Path:
    v = manifest_video(video_id)
    meta = {
        "video_id": video_id,
        "title": v["title"],
        "course": v["course"],
        "course_label": COURSE_LABELS.get(v["course"], v["course"]),
        "url": v["url"],
        "duration_sec": v.get("duration"),
    }
    path = lesson_meta_path(video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def lesson_transcript_dir(video_id: str) -> Path:
    return lesson_dir(video_id) / "transcript"


def video_path(video_id: str, height: int = 1080) -> Path:
    return lesson_dir(video_id) / f"video_{height}p.mp4"


def board_work_dir(video_id: str, height: int = 1080) -> Path:
    return lesson_dir(video_id) / "board" / f"h{height}"


def board_ocr_dir(video_id: str) -> Path:
    return lesson_dir(video_id) / "board" / "ocr"


def board_crops_dir(video_id: str) -> Path:
    return lesson_dir(video_id) / "board" / "crops"


def skill_latex_dir(video_id: str) -> Path:
    return BOARD_NOTES_DIR / video_id / "latex"


def skill_board_index_path(video_id: str) -> Path:
    return BOARD_NOTES_DIR / video_id / "board_index.json"


def process_rel(path: Path) -> str:
    return path.relative_to(YOUTUBE_PROCESS_ROOT).as_posix()


def skill_rel(path: Path) -> str:
    return path.relative_to(SKILL_ROOT).as_posix()


def relpath_from(base: Path, target: Path) -> str:
    return os.path.relpath(target, base).replace("\\", "/")


def clear_manifest_cache() -> None:
    manifest_by_id.cache_clear()
