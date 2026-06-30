#!/usr/bin/env python3
"""Board frames (YouTubeProcess) -> LaTeX + PNG in Skill; page toggles LaTeX / photo.

Usage:
  python board_to_latex.py --video-id nocZR2m180M --all
  python board_to_latex.py --video-id nocZR2m180M --scenes 6,9,20
  python board_to_latex.py --video-id nocZR2m180M --all --pix2tex
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from cv2_unicode import imread as cv_imread
from cv2_unicode import imwrite as cv_imwrite
from youtube_process_paths import (
    PIX2TEX_VENV,
    SKILL_ROOT,
    YOUTUBE_PROCESS_ROOT,
    board_crops_dir,
    board_ocr_dir,
    board_work_dir,
    lesson_dir,
    process_rel,
    skill_board_index_path,
    skill_latex_dir,
    skill_rel,
    write_lesson_meta,
)

PIX2TEX_INFER = SKILL_ROOT / "scripts" / "pix2tex_infer.py"
RENDER_PREVIEW = SKILL_ROOT / "scripts" / "render_latex_preview.py"

GREEN_LOWER = np.array([35, 40, 40])
GREEN_UPPER = np.array([85, 255, 255])

FALLBACK_LATEX: dict[int, dict[str, str]] = {
    6: {
        "label": "1.1 Vector algebra",
        "body": r"""
\textbf{1. Vectors and Fields} \\
\textbf{1.1 Vector algebra} \quad 3D
\begin{align*}
\vec{A} &= A_1\hat{a}_1 + A_2\hat{a}_2 + A_3\hat{a}_3 \\
|\vec{A}| &= \sqrt{A_1^2 + A_2^2 + A_3^2} = A \\
\hat{a}_A &= \frac{\vec{A}}{|\vec{A}|}, \quad |\hat{a}_A| = 1
\end{align*}
""",
    },
    9: {
        "label": "Addition & Dot product",
        "body": r"""
\textbf{Addition}
\begin{align*}
\vec{A} \pm \vec{B} &= (A_1 \pm B_1)\hat{a}_1 + (A_2 \pm B_2)\hat{a}_2 + (A_3 \pm B_3)\hat{a}_3 \\
m\vec{A} &= mA_1\hat{a}_1 + mA_2\hat{a}_2 + mA_3\hat{a}_3
\end{align*}
\textbf{Dot product}
\begin{align*}
\vec{A}\cdot\vec{B} &= AB\cos\alpha = A_1B_1 + A_2B_2 + A_3B_3
\end{align*}
""",
    },
    20: {
        "label": "Cross & triple product",
        "body": r"""
\textbf{Cross product}
\begin{align*}
\vec{A}\times\vec{B} &= AB\sin\alpha\,\hat{n}
\end{align*}
\textbf{Vector triple product (P17)}
\begin{align*}
\vec{A}\times(\vec{B}\times\vec{C}) &= \vec{B}(\vec{A}\cdot\vec{C}) - \vec{C}(\vec{A}\cdot\vec{B})
\end{align*}
""",
    },
}


def log(msg: str) -> None:
    print(msg, flush=True)


def load_ocr_frames(video_id: str) -> list[dict]:
    ocr_dir = board_ocr_dir(video_id)
    for fp in sorted(ocr_dir.glob("board_ocr*.json"), key=lambda p: ("full" not in p.name, p.name), reverse=True):
        data = json.loads(fp.read_text(encoding="utf-8"))
        frames = data.get("frames") or []
        if frames:
            return frames
    return []


def load_scene_timestamps(video_id: str) -> dict[int, float]:
    return {int(f["index"]): float(f["timestamp_sec"]) for f in load_ocr_frames(video_id)}


def detect_board_crop(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        x, y, bw, bh = cv2.boundingRect(c)
        if bw * bh > 0.15 * w * h:
            pad = 8
            return frame[max(0, y - pad) : min(h, y + bh + pad), max(0, x - pad) : min(w, x + bw + pad)]
    return frame[int(h * 0.05) : h - int(h * 0.05), int(w * 0.02) : w - int(w * 0.02)]


def escape_tex_text(text: str) -> str:
    out = text.replace("\\", r"\textbackslash ")
    for ch in "&%$#_{}":
        out = out.replace(ch, f"\\{ch}")
    return out


def first_label_line(ocr_text: str, scene_idx: int) -> str:
    for line in ocr_text.splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return f"場景 {scene_idx}"


def is_usable_pix2tex(raw: str) -> bool:
    if not raw or len(raw) < 4 or len(raw) > 800:
        return False
    if raw.count("{") > 40 or raw.count("\\") > 80:
        return False
    return any(tok in raw for tok in (r"\frac", r"\vec", r"\sqrt", r"\sum", r"\int", "^", "_"))


GREEK_MAP = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "θ": r"\theta", "λ": r"\lambda", "μ": r"\mu", "π": r"\pi",
    "σ": r"\sigma", "φ": r"\phi", "ω": r"\omega", "Δ": r"\Delta",
    "∇": r"\nabla", "∞": r"\infty",
}

MATH_LINE_RE = re.compile(
    r"[=+\-*/^√∫∑∏×·\\]|\\frac|\\vec|\\hat|\\sqrt|[αβγδθλμπσφωΔ∇]"
)


def ocr_line_to_math_expr(line: str) -> str | None:
    s = line.strip()
    if not s or len(s) > 240:
        return None
    if not MATH_LINE_RE.search(s) and not re.search(r"[A-Za-z]\s*[_^]\s*[\w{]", s):
        if "=" not in s and not re.search(r"\d+\s*[/\\]\s*\d+", s):
            return None
    s = re.sub(r"\s+", " ", s)
    s = s.replace("×", r" \times ").replace("·", r" \cdot ").replace("÷", r" \div ")
    s = s.replace("−", "-").replace("–", "-")
    for ch, tex in GREEK_MAP.items():
        s = s.replace(ch, f" {tex} ")
    s = re.sub(r"\^(\w+)", r"^{\1}", s)
    s = re.sub(r"_(\w+)", r"_{\1}", s)
    s = re.sub(r"([A-Za-z])(\d+)\b", r"\1_{\2}", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s else None


def assess_latex_quality(video_id: str, scene_idx: int, pix_raw: str | None, use_pix2tex: bool) -> str:
    if video_id == "nocZR2m180M" and scene_idx in FALLBACK_LATEX:
        return "template"
    if use_pix2tex and pix_raw and is_usable_pix2tex(pix_raw):
        return "pix2tex"
    return "photo_only"


def build_latex_body(
    scene_idx: int,
    ocr_text: str,
    pix_raw: str | None,
    video_id: str,
) -> tuple[str, str]:
    if video_id == "nocZR2m180M" and scene_idx in FALLBACK_LATEX:
        meta = FALLBACK_LATEX[scene_idx]
        return meta["label"], meta["body"]

    label = first_label_line(ocr_text, scene_idx)
    if pix_raw and is_usable_pix2tex(pix_raw):
        return label, f"\\begin{{align*}}\n{pix_raw}\n\\end{{align*}}"

    raise ValueError("photo_only")


def pix2tex_python() -> Path | None:
    override = os.environ.get("PIX2TEX_PYTHON")
    if override:
        p = Path(override)
        return p if p.is_file() else None
    for name in ("python.exe", "python"):
        candidate = PIX2TEX_VENV / "Scripts" / name
        if candidate.is_file():
            return candidate
        candidate = PIX2TEX_VENV / "bin" / name
        if candidate.is_file():
            return candidate
    return None


def try_pix2tex(pil_img: Image.Image, crop_path: Path) -> str | None:
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    venv_py = pix2tex_python()
    if venv_py and PIX2TEX_INFER.is_file():
        try:
            proc = subprocess.run(
                [str(venv_py), str(PIX2TEX_INFER), str(crop_path)],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception as exc:  # noqa: BLE001
            log(f"  pix2tex skipped: {exc}")
    return None


def render_png(tex_path: Path, png_path: Path) -> bool:
    venv_py = pix2tex_python()
    py = venv_py or Path(os.environ.get("PYTHON", "python"))
    try:
        proc = subprocess.run(
            [str(py), str(RENDER_PREVIEW), str(tex_path), "-o", str(png_path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return proc.returncode == 0 and png_path.is_file()
    except Exception as exc:  # noqa: BLE001
        log(f"  PNG render failed: {exc}")
        return False


def write_tex_document(
    video_id: str,
    scene_idx: int,
    timestamp_sec: float,
    label: str,
    body: str,
    pix2tex_raw: str | None,
    out_tex: Path,
) -> None:
    title = f"{label} ({int(timestamp_sec)}s)"
    lines = [
        r"\documentclass[border=8pt]{standalone}",
        r"\usepackage{amsmath,amssymb}",
        r"\begin{document}",
        f"% video_id: {video_id}",
        f"% scene_index: {scene_idx}",
        f"% timestamp_sec: {timestamp_sec}",
        f"% {title}",
    ]
    if pix2tex_raw:
        lines.append(f"% pix2tex_raw: {pix2tex_raw[:200]}")
    lines.append(body.strip())
    lines.append(r"\end{document}")
    out_tex.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_crop(video_id: str, scene_idx: int, frame: dict | None) -> Path:
    crop_dir = board_crops_dir(video_id)
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_path = crop_dir / f"scene_{scene_idx:04d}_crop.jpg"
    if crop_path.is_file():
        return crop_path

    if frame:
        for key in ("enhanced_path", "image_path"):
            rel = frame.get(key)
            if rel:
                src = YOUTUBE_PROCESS_ROOT / Path(str(rel).replace("\\", "/"))
                if src.is_file():
                    img = cv_imread(src)
                    if img is not None:
                        cv_imwrite(crop_path, img)
                        return crop_path

    frame_path = board_work_dir(video_id, 1080) / "frames" / f"scene_{scene_idx:04d}.jpg"
    if frame_path.is_file():
        img = cv_imread(frame_path)
        if img is not None:
            cv_imwrite(crop_path, detect_board_crop(img))
    return crop_path


def process_scene(
    video_id: str,
    scene_idx: int,
    out_dir: Path,
    timestamps: dict[int, float],
    frame: dict | None,
    use_pix2tex: bool,
) -> dict:
    ts = float((frame or {}).get("timestamp_sec") or timestamps.get(scene_idx, 0.0))
    ocr_text = (frame or {}).get("ocr_text") or ""
    crop_path = ensure_crop(video_id, scene_idx, frame)

    pix_raw = None
    if use_pix2tex and crop_path.is_file():
        img = cv_imread(crop_path)
        if img is not None:
            pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            pix_raw = try_pix2tex(pil, crop_path)

    quality = assess_latex_quality(video_id, scene_idx, pix_raw, use_pix2tex)
    label = first_label_line(ocr_text, scene_idx)
    title = f"{label} ({int(ts)}s)"

    source_enhanced = (frame or {}).get("enhanced_path")
    source_frame = (frame or {}).get("image_path")
    if not source_enhanced and crop_path.is_file():
        source_enhanced = process_rel(crop_path)

    tex_path = out_dir / f"scene_{scene_idx:04d}.tex"
    png_path = out_dir / f"scene_{scene_idx:04d}.png"

    base = {
        "scene": scene_idx,
        "timestamp_sec": ts,
        "title": title,
        "label": label,
        "latex_quality": quality,
        "source_frame": source_frame,
        "source_enhanced": source_enhanced,
        "source_crop": process_rel(crop_path) if crop_path.is_file() else None,
        "ocr_text": ocr_text,
        "pix2tex_raw": pix_raw,
    }

    if quality == "photo_only":
        for stale in (tex_path, png_path):
            if stale.is_file():
                stale.unlink()
        log(f"  scene {scene_idx:04d}: photo_only (no LaTeX PNG)")
        return {**base, "tex": None, "png": None}

    label, body = build_latex_body(scene_idx, ocr_text, pix_raw, video_id)
    title = f"{label} ({int(ts)}s)"
    write_tex_document(video_id, scene_idx, ts, label, body, pix_raw, tex_path)
    if not render_png(tex_path, png_path):
        log(f"  warning: PNG not generated for scene {scene_idx:04d}; fallback photo_only")
        for stale in (tex_path, png_path):
            if stale.is_file():
                stale.unlink()
        return {**base, "title": title, "label": label, "latex_quality": "photo_only", "tex": None, "png": None}

    log(f"  scene {scene_idx:04d}: {quality}")
    return {
        **base,
        "title": title,
        "label": label,
        "tex": skill_rel(tex_path),
        "png": skill_rel(png_path) if png_path.is_file() else None,
    }


def write_board_index(video_id: str, scenes: list[dict]) -> None:
    from youtube_process_paths import COURSE_LABELS, manifest_video

    v = manifest_video(video_id)
    index_path = skill_board_index_path(video_id)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "video_id": video_id,
        "title": v["title"],
        "course": v["course"],
        "course_label": COURSE_LABELS.get(v["course"], v["course"]),
        "youtube_url": v["url"],
        "lesson_folder": lesson_dir(video_id).relative_to(YOUTUBE_PROCESS_ROOT).as_posix()
        if lesson_dir(video_id).exists()
        else None,
        "generated": datetime.now(timezone.utc).isoformat(),
        "scenes": scenes,
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Board -> LaTeX + PNG (Skill); raw assets in YouTubeProcess")
    parser.add_argument("--video-id", default="nocZR2m180M")
    parser.add_argument("--scenes", default="", help="comma-separated scene indices")
    parser.add_argument("--all", action="store_true", help="all OCR frames for this video")
    parser.add_argument("--no-pix2tex", action="store_true", help="skip pix2tex (only manual templates get LaTeX)")
    args = parser.parse_args()

    frames = load_ocr_frames(args.video_id)
    by_idx = {int(f["index"]): f for f in frames}
    timestamps = load_scene_timestamps(args.video_id)
    use_pix2tex = not args.no_pix2tex

    if args.all:
        scenes_idx = sorted(by_idx.keys())
    elif args.scenes.strip():
        scenes_idx = [int(s.strip()) for s in args.scenes.split(",") if s.strip()]
    else:
        scenes_idx = [6, 9, 20] if args.video_id == "nocZR2m180M" else sorted(by_idx.keys())

    if not scenes_idx:
        log(f"No OCR frames for {args.video_id}; run extract_board_frames.py first.")
        return 1

    out_dir = skill_latex_dir(args.video_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for idx in scenes_idx:
        log(f"Processing scene {idx:04d} @ {int(timestamps.get(idx, 0))}s...")
        results.append(process_scene(args.video_id, idx, out_dir, timestamps, by_idx.get(idx), use_pix2tex))

    write_board_index(args.video_id, results)
    log(f"Board index: {skill_board_index_path(args.video_id)} ({len(results)} scenes)")

    write_lesson_meta(args.video_id)
    idx_script = SKILL_ROOT / "scripts" / "build_youtube_process_index.py"
    subprocess.run([sys.executable, str(idx_script)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
