#!/usr/bin/env python3
"""Upload trimmed GROQ_API_KEY from worker/.dev.vars to Cloudflare Worker."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV_VARS = ROOT / "worker" / ".dev.vars"


def load_groq_key() -> str:
    if not DEV_VARS.exists():
        raise SystemExit(f"Missing {DEV_VARS} — copy from worker/.dev.vars.example")
    for line in DEV_VARS.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        name, value = s.split("=", 1)
        if name.strip() == "GROQ_API_KEY":
            key = value.strip().strip('"').strip("'")
            if not key or "your_groq" in key:
                raise SystemExit("GROQ_API_KEY in .dev.vars is empty or still a placeholder")
            if not key.startswith("gsk_"):
                raise SystemExit("GROQ_API_KEY should start with gsk_ — check Groq console")
            return key
    raise SystemExit("GROQ_API_KEY not found in worker/.dev.vars")


def main() -> int:
    key = load_groq_key()
    print(f"Uploading GROQ_API_KEY (len={len(key)}) to em-lab-pi-chat …")
    proc = subprocess.run(
        "npx wrangler secret put GROQ_API_KEY",
        cwd=ROOT / "worker",
        input=key,
        text=True,
        capture_output=True,
        shell=True,
    )
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.returncode != 0:
        print(proc.stderr or "wrangler secret put failed", file=sys.stderr)
        return proc.returncode
    print("Done. Secret updated (Worker auto-publishes new version).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
