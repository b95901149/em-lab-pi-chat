#!/usr/bin/env python3
"""Run pix2tex on one image; print LaTeX to stdout. For subprocess from board_to_latex."""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=str, help="path to board crop image")
    args = parser.parse_args()

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    from pix2tex.cli import LatexOCR  # noqa: WPS433

    img = Image.open(args.image).convert("RGB")
    model = LatexOCR()
    print(str(model(img)).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
