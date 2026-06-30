#!/usr/bin/env python3
"""Extract chalkboard text from YouTube lecture videos (pilot).

Pipeline: download → scene-change frames → green-board crop → enhance → OCR → dedup.

Usage:
  python extract_board_frames.py --video-id nocZR2m180M
  python extract_board_frames.py --video-id nocZR2m180M --max-scenes 20 --end-sec 600
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np

from cv2_unicode import imread as cv_imread
from cv2_unicode import imwrite as cv_imwrite
from youtube_process_paths import (
    MANIFEST_PATH,
    SKILL_ROOT,
    YOUTUBE_PROCESS_ROOT,
    board_ocr_dir,
    board_work_dir,
    lesson_dir,
    process_rel,
    video_path,
    write_lesson_meta,
)
YTDLP = Path(r"C:\ProgramData\anaconda3\Scripts\yt-dlp.exe")
FFMPEG = Path(r"C:\ProgramData\anaconda3\Library\bin\ffmpeg.exe")

# Green chalkboard HSV (NTU classroom style)
GREEN_LOWER = np.array([35, 40, 40])
GREEN_UPPER = np.array([85, 255, 255])


@dataclass
class BoardFrame:
    index: int
    timestamp_sec: float
    image_path: str
    enhanced_path: str
    ocr_text: str
    ocr_confidence: float


@dataclass
class BoardExtractionResult:
    video_id: str
    title: str
    resolution: str
    video_duration_sec: float
    coverage_end_sec: float
    scenes_extracted: int
    unique_board_pages: int
    frames: list[BoardFrame]
    merged_text: str
    notes: list[str]
    timing: dict[str, float]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_manifest_entry(video_id: str) -> dict:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for v in data["videos"]:
        if v["id"] == video_id:
            return v
    raise SystemExit(f"video id not in manifest: {video_id}")


def download_video(video_id: str, url: str, dest: Path, max_height: int = 480) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"video_{max_height}p.mp4"
    if out.exists() and out.stat().st_size > 1_000_000:
        log(f"Using cached video: {out}")
        return out
    cmd = [
        str(YTDLP),
        "-f", f"bv*[height<={max_height}]+ba/b[height<=1080]/best",
        "--merge-output-format", "mp4",
        "--extractor-args", "youtube:player_client=android",
        "-o", str(dest / f"video_{max_height}p.%(ext)s"),
        "--no-playlist",
        "--retries", "5",
        "--fragment-retries", "5",
        url,
    ]
    log(f"Downloading video (max {max_height}p)...")
    subprocess.run(cmd, check=True)
    from video_utils import ensure_faststart

    if ensure_faststart(out):
        log(f"Remuxed for faststart (browser seek): {out}")
    return out


def extract_scene_frames(
    video_path: Path,
    frames_dir: Path,
    scene_threshold: float,
    start_sec: float,
    end_sec: float | None,
    max_scenes: int,
) -> list[tuple[int, float]]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("scene_*.jpg"):
        old.unlink()

    vf_parts = [f"select='gt(scene,{scene_threshold})'", "showinfo"]
    if start_sec > 0:
        vf_parts.insert(0, f"trim=start={start_sec}" + (f":end={end_sec}" if end_sec else "") + ",setpts=PTS-STARTPTS")
    vf = ",".join(vf_parts)

    cmd = [
        str(FFMPEG), "-y", "-i", str(video_path),
        "-vf", vf,
        "-vsync", "vfr",
        "-frames:v", str(max_scenes),
        str(frames_dir / "scene_%04d.jpg"),
    ]
    log(f"Extracting scene frames (threshold={scene_threshold}, max={max_scenes})...")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        log(proc.stderr[-800:])

    timestamps: list[tuple[int, float]] = []
    for line in proc.stderr.splitlines():
        m = re.search(r"n:\s*(\d+).*pts_time:([\d.]+)", line)
        if m:
            timestamps.append((int(m.group(1)), float(m.group(2)) + start_sec))

    files = sorted(frames_dir.glob("scene_*.jpg"))
    if not files:
        # fallback: uniform sampling every 60s
        log("No scene frames; falling back to uniform sampling every 60s")
        duration = end_sec or 600
        step = max(45, int((duration - start_sec) / max_scenes))
        for i, t in enumerate(range(int(start_sec), int(duration), step)):
            out = frames_dir / f"scene_{i+1:04d}.jpg"
            subprocess.run(
                [str(FFMPEG), "-y", "-ss", str(t), "-i", str(video_path), "-frames:v", "1", str(out)],
                check=True,
                capture_output=True,
            )
            timestamps.append((i + 1, float(t)))
        files = sorted(frames_dir.glob("scene_*.jpg"))

    result: list[tuple[int, float]] = []
    for i, fp in enumerate(files):
        ts = timestamps[i][1] if i < len(timestamps) else float(i * 60)
        result.append((i + 1, ts))
    return result


def detect_board_crop(frame: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        x, y, bw, bh = cv2.boundingRect(c)
        if bw * bh > 0.15 * w * h:
            pad = 8
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w, x + bw + pad)
            y2 = min(h, y + bh + pad)
            return frame[y1:y2, x1:x2], (x1, y1, x2, y2)

    # fallback: central crop (board usually fills frame)
    margin_x, margin_y = int(w * 0.02), int(h * 0.05)
    crop = frame[margin_y : h - margin_y, margin_x : w - margin_x]
    return crop, (margin_x, margin_y, w - margin_x, h - margin_y)


def enhance_for_ocr(board: np.ndarray) -> np.ndarray:
    """Boost chalk contrast: CLAHE + Otsu binarization, upscale for OCR."""
    gray = cv2.cvtColor(board, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    # chalk is bright on dark green board → invert then threshold
    inv = cv2.bitwise_not(gray)
    _, binary = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    scale = 2.5 if max(board.shape[:2]) < 900 else 1.5
    return cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def run_ocr(engine, image: np.ndarray) -> tuple[str, float]:
    result, _ = engine(image)
    if not result:
        return "", 0.0
    texts: list[str] = []
    confs: list[float] = []
    for item in result:
        if len(item) >= 3:
            texts.append(str(item[1]).strip())
            confs.append(float(item[2]))
    merged = "\n".join(t for t in texts if t)
    avg_conf = sum(confs) / len(confs) if confs else 0.0
    return merged, avg_conf


def text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def dedup_frames(frames: list[BoardFrame], threshold: float = 0.82) -> list[BoardFrame]:
    unique: list[BoardFrame] = []
    for fr in frames:
        if any(text_similarity(fr.ocr_text, u.ocr_text) >= threshold for u in unique if fr.ocr_text.strip() and u.ocr_text.strip()):
            continue
        unique.append(fr)
    return unique


def process_video(
    video_id: str,
    scene_threshold: float,
    max_scenes: int,
    start_sec: float,
    end_sec: float | None,
    _langs: list[str],
    max_height: int = 480,
) -> BoardExtractionResult:
    t0 = time.perf_counter()
    entry = load_manifest_entry(video_id)
    title = entry["title"]
    duration = float(entry.get("duration") or 0)
    ld = lesson_dir(video_id)
    ld.mkdir(parents=True, exist_ok=True)
    write_lesson_meta(video_id)
    frames_dir = board_work_dir(video_id, max_height) / "frames"
    enhanced_dir = board_work_dir(video_id, max_height) / "enhanced"
    enhanced_dir.mkdir(parents=True, exist_ok=True)

    t_dl = time.perf_counter()
    vfile = download_video(video_id, entry["url"], ld, max_height=max_height)
    download_sec = time.perf_counter() - t_dl

    scene_list = extract_scene_frames(
        vfile, frames_dir, scene_threshold, start_sec, end_sec, max_scenes
    )

    log("Loading RapidOCR model...")
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    t_ocr = time.perf_counter()

    frames: list[BoardFrame] = []
    for idx, ts in scene_list:
        fp = frames_dir / f"scene_{idx:04d}.jpg"
        if not fp.exists():
            continue
        img = cv_imread(fp)
        if img is None:
            continue
        board, _ = detect_board_crop(img)
        enhanced = enhance_for_ocr(board)
        enh_path = enhanced_dir / f"scene_{idx:04d}.png"
        cv_imwrite(enh_path, enhanced)
        text, conf = run_ocr(engine, enhanced)
        if len(text.strip()) < 8:
            # fallback: OCR on upscaled raw board crop
            up = cv2.resize(board, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            text2, conf2 = run_ocr(engine, up)
            if len(text2.strip()) > len(text.strip()):
                text, conf = text2, conf2
        frames.append(
            BoardFrame(
                index=idx,
                timestamp_sec=ts,
                image_path=process_rel(fp),
                enhanced_path=process_rel(enh_path),
                ocr_text=text,
                ocr_confidence=round(conf, 3),
            )
        )
        log(f"  [{idx:02d}] t={ts:6.0f}s conf={conf:.2f} chars={len(text)}")

    ocr_sec = time.perf_counter() - t_ocr
    unique = dedup_frames(frames)
    merged = "\n\n---\n\n".join(
        f"[{int(f.timestamp_sec)}s]\n{f.ocr_text}" for f in unique if f.ocr_text.strip()
    )

    notes = [
        "綠板自動裁切 + 白字強化後送 RapidOCR（ONNX）。",
        "英文板書與簡單公式效果較佳；複雜向量式、分數、遮擋會掉字。",
        "建議與 ASR 逐字稿交叉對照，不單獨當 ground truth。",
    ]

    return BoardExtractionResult(
        video_id=video_id,
        title=title,
        resolution=f"{max_height}p",
        video_duration_sec=duration,
        coverage_end_sec=float(end_sec or duration or 0),
        scenes_extracted=len(frames),
        unique_board_pages=len(unique),
        frames=frames,
        merged_text=merged,
        notes=notes,
        timing={
            "download_sec": round(download_sec, 2),
            "ocr_sec": round(ocr_sec, 2),
            "total_sec": round(time.perf_counter() - t0, 2),
            "sec_per_frame": round(ocr_sec / max(len(frames), 1), 2),
        },
    )


def is_full_coverage(result: BoardExtractionResult) -> bool:
    if not result.video_duration_sec:
        return False
    return result.coverage_end_sec >= result.video_duration_sec * 0.95


def result_suffix(result: BoardExtractionResult) -> str:
    base = f"_{result.resolution}" if result.resolution else ""
    return f"{base}_full" if is_full_coverage(result) else base


def save_result(result: BoardExtractionResult) -> Path:
    out_dir = board_ocr_dir(result.video_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = result_suffix(result)
    md_path = out_dir / f"board_ocr{suffix}.md"
    md_lines = [
        f"# {result.title}",
        "",
        f"- video_id: `{result.video_id}`",
        f"- resolution: {result.resolution}",
        f"- video_duration_sec: {result.video_duration_sec}",
        f"- coverage_end_sec: {result.coverage_end_sec}",
        f"- full_lecture: {is_full_coverage(result)}",
        f"- scenes OCR: {result.scenes_extracted}",
        f"- unique pages (deduped): {result.unique_board_pages}",
        f"- timing: {json.dumps(result.timing, ensure_ascii=False)}",
        f"- generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Notes",
        *[f"- {n}" for n in result.notes],
        "",
        "## Merged board text",
        "",
        result.merged_text or "_(no text detected)_",
        "",
        "## Per-frame",
        "",
    ]
    for f in result.frames:
        enh = f.enhanced_path.replace("\\", "/")
        md_lines += [
            f"### Scene {f.index} @ {int(f.timestamp_sec)}s (conf={f.ocr_confidence})",
            "",
            f"![]({YOUTUBE_PROCESS_ROOT.name}/{enh})",
            "",
            "```",
            f.ocr_text or "(empty)",
            "```",
            "",
        ]
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    json_path = out_dir / f"board_ocr{suffix}.json"
    payload = asdict(result)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Pilot: extract chalkboard OCR from lecture video")
    parser.add_argument("--video-id", default="nocZR2m180M", help="YouTube video id")
    parser.add_argument("--scene-threshold", type=float, default=0.22)
    parser.add_argument("--max-scenes", type=int, default=25, help="max scene frames to OCR")
    parser.add_argument("--start-sec", type=float, default=0)
    parser.add_argument("--end-sec", type=float, default=0, help="process until N seconds (0 = use --full or 900)")
    parser.add_argument("--full", action="store_true", help="process entire lecture from manifest duration")
    parser.add_argument("--height", type=int, default=480, choices=[360, 480, 720, 1080], help="max video height")
    parser.add_argument("--langs", default="en,ch_tra", help="unused (RapidOCR)")
    parser.add_argument("--benchmark", action="store_true", help="write benchmark.md after run")
    args = parser.parse_args()

    entry = load_manifest_entry(args.video_id)
    duration = float(entry.get("duration") or 1600)
    if args.full:
        end_sec = duration
        max_scenes = args.max_scenes if args.max_scenes != 25 else int(duration / 60) + 2
    else:
        end_sec = args.end_sec if args.end_sec > 0 else 900
        max_scenes = args.max_scenes

    langs = [s.strip() for s in args.langs.split(",") if s.strip()]
    log(f"Board OCR: {args.video_id} @ {args.height}p | 0–{end_sec:.0f}s | max_scenes={max_scenes}")
    result = process_video(
        args.video_id,
        args.scene_threshold,
        max_scenes,
        args.start_sec,
        end_sec,
        langs,
        max_height=args.height,
    )
    out = save_result(result)
    log("")
    log(f"Done: {result.scenes_extracted} scenes, {result.unique_board_pages} unique pages")
    log(f"Timing: {result.timing}")
    log(f"Report: {out}")
    if args.benchmark:
        bench = SKILL_ROOT / "scripts" / "build_board_benchmark.py"
        subprocess.run([sys.executable, str(bench), "--video-id", args.video_id], check=False)
    idx = SKILL_ROOT / "scripts" / "build_youtube_process_index.py"
    subprocess.run([sys.executable, str(idx)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
