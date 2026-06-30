#!/usr/bin/env python3
"""Prepare Zordon base + soft hologram face for CSS CRT overlay."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ZORDON = (
    Path(r"C:\Users\clin\.cursor\projects\d-cursor-cheng-yu-hsiang-perspective-1-0")
    / "assets"
    / "c__Users_clin_AppData_Roaming_Cursor_User_workspaceStorage_3992d02e357176ca8740dca7ce4fc34e_images_image-4fb77a86-54a8-44df-9cfe-424845175d51.png"
)
DEFAULT_FACE = (
    Path(r"C:\Users\clin\.cursor\projects\d-cursor-cheng-yu-hsiang-perspective-1-0")
    / "assets"
    / "c__Users_clin_AppData_Roaming_Cursor_User_workspaceStorage_3992d02e357176ca8740dca7ce4fc34e_images_image-30216add-a381-4060-a5a3-6c8a38d62431.png"
)
OUT_DIR = SKILL_ROOT / "web" / "assets"

FACE_CX = 0.50
FACE_CY = 0.385
FACE_RADIUS = 0.355
MASK_FEATHER = 14


def remove_bg_soft(img: Image.Image, threshold: int = 238, feather: int = 6) -> Image.Image:
    img = img.convert("RGBA")
    arr = np.array(img, dtype=np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    lum = (r + g + b) / 3.0
    alpha = np.clip((255 - lum) / max(255 - threshold, 1) * 255, 0, 255)
    arr[:, :, 3] = np.minimum(a, alpha)
    if feather > 0:
        mask = Image.fromarray(arr[:, :, 3].astype(np.uint8), mode="L")
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
        arr[:, :, 3] = np.array(mask, dtype=np.float32)
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


def cylinder_mask(size: tuple[int, int], feather: int = MASK_FEATHER) -> Image.Image:
    """Soft vertical-ellipse mask — fades into tube, no hard ring."""
    w, h = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((w * 0.04, h * 0.02, w * 0.96, h * 0.98), fill=255)
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask


def crop_circular_face(
    img: Image.Image,
    cx: float = FACE_CX,
    cy: float = FACE_CY,
    radius: float = FACE_RADIUS,
) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    cx_px = int(w * cx)
    cy_px = int(h * cy)
    r_px = int(min(w, h) * radius)

    left = max(cx_px - r_px, 0)
    top = max(cy_px - r_px, 0)
    right = min(cx_px + r_px, w)
    bottom = min(cy_px + r_px, h)
    return img.crop((left, top, right, bottom))


def ghost_tint(face: Image.Image, opacity: float = 0.72) -> Image.Image:
    toned = ImageEnhance.Color(face).enhance(0.22)
    toned = ImageEnhance.Brightness(toned).enhance(1.42)
    toned = ImageEnhance.Contrast(toned).enhance(0.72)

    arr = np.array(toned, dtype=np.float32)
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    r = r * 0.5 + 90
    g = g * 0.68 + 145
    b = b * 0.88 + 210
    arr[:, :, 0] = np.clip(r, 0, 255)
    arr[:, :, 1] = np.clip(g, 0, 255)
    arr[:, :, 2] = np.clip(b, 0, 255)
    arr[:, :, 3] = a * opacity
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


def soften_tube_area(bg: Image.Image) -> Image.Image:
    w, h = bg.size
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx = w // 2
    cy = int(h * 0.27)
    rx, ry = int(w * 0.18), int(h * 0.24)
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(15, 35, 70, 165))
    overlay = overlay.filter(ImageFilter.GaussianBlur(22))
    return Image.alpha_composite(bg.convert("RGBA"), overlay)


def prepare_holo(face_path: Path, out_size: int = 512) -> Image.Image:
    raw = remove_bg_soft(Image.open(face_path))
    face = crop_circular_face(raw)
    face = ghost_tint(face)
    mask = cylinder_mask(face.size)
    face.putalpha(ImageChops.multiply(face.split()[3], mask))
    return face.resize((out_size, out_size), Image.Resampling.LANCZOS)


def compose(zordon_path: Path, face_path: Path, out_dir: Path) -> None:
    base = soften_tube_area(Image.open(zordon_path))

    holo = prepare_holo(face_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out_dir / "zordon-base.jpg", quality=92)
    holo.save(out_dir / "pi-holo.png")
    # fallback single image for non-CSS contexts
    preview = base.copy()
    diameter = int(base.size[0] * 0.34)
    holo_s = holo.resize((diameter, diameter), Image.Resampling.LANCZOS)
    px = (base.size[0] - diameter) // 2
    py = int(base.size[1] * 0.07)
    for blur, alpha in [(24, 0.15), (10, 0.28)]:
        glow = holo_s.copy().filter(ImageFilter.GaussianBlur(blur))
        glow.putalpha(ImageEnhance.Brightness(glow.split()[3]).enhance(alpha))
        preview.paste(glow, (px, py), glow)
    layer = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    layer.paste(holo_s, (px, py), holo_s)
    preview = Image.alpha_composite(preview, layer)
    preview.convert("RGB").save(out_dir / "pi-command-center.jpg", quality=92)
    print(f"Wrote zordon-base.jpg + pi-holo.png ({holo.size[0]}px)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zordon", type=Path, default=DEFAULT_ZORDON)
    parser.add_argument("--face", type=Path, default=DEFAULT_FACE)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    compose(args.zordon, args.face, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
