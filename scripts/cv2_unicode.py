"""OpenCV I/O helpers for Unicode paths on Windows."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path: Path | str) -> np.ndarray | None:
    p = Path(path)
    if not p.is_file():
        return None
    data = np.fromfile(str(p), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite(path: Path | str, image: np.ndarray) -> bool:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix if p.suffix else ".png"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        return False
    buf.tofile(str(p))
    return True
