"""MP4 helpers for browser-friendly playback (faststart / seekable)."""

from __future__ import annotations

import subprocess
from pathlib import Path

FFMPEG = Path(r"C:\ProgramData\anaconda3\Library\bin\ffmpeg.exe")


def moov_before_mdat(path: Path) -> bool:
    data = path.read_bytes()
    moov = data.find(b"moov")
    mdat = data.find(b"mdat")
    if moov < 0 or mdat < 0:
        return False
    return moov < mdat


def ensure_faststart(path: Path) -> bool:
    """Remux in place so moov is at file start. Returns True if remuxed."""
    if not path.is_file() or path.stat().st_size < 1_000_000:
        return False
    if moov_before_mdat(path):
        return False
    tmp = path.with_suffix(path.suffix + ".faststart.tmp")
    cmd = [
        str(FFMPEG),
        "-y",
        "-i",
        str(path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not tmp.is_file():
        if tmp.is_file():
            tmp.unlink()
        raise RuntimeError(proc.stderr[-500:] if proc.stderr else "ffmpeg faststart failed")
    tmp.replace(path)
    return True
