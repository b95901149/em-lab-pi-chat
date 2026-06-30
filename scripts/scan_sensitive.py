#!/usr/bin/env python3
"""Scan tracked git files for sensitive strings (secrets, corpus paths, PII patterns)."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".woff",
    ".woff2",
    ".ico",
    ".lock",
}

PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "groq_api_key",
        re.compile(r"gsk_[A-Za-z0-9]{20,}"),
        "Groq API key",
    ),
    (
        "gemini_api_key",
        re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),
        "Google/Gemini API key",
    ),
    (
        "openai_key",
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        "OpenAI-style API key",
    ),
    (
        "bearer_secret",
        re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{24,}"),
        "Bearer token",
    ),
    (
        "line_corpus_path",
        re.compile(r"references/sources/line/", re.I),
        "LINE raw corpus path",
    ),
    (
        "ptt_corpus_path",
        re.compile(r"references/sources/ptt/", re.I),
        "PTT raw corpus path",
    ),
    (
        "line_messages_file",
        re.compile(r"chengfred_line_messages\.txt", re.I),
        "LINE messages filename",
    ),
    (
        "ptt_export_file",
        re.compile(r"chengfred_pttweb\.json", re.I),
        "PTT export filename",
    ),
    (
        "dev_vars_real",
        re.compile(r"^GROQ_API_KEY=(?!your_groq_api_key_here)[^\s#]+$", re.M),
        "GROQ_API_KEY in file (not placeholder)",
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "Email address",
    ),
    (
        "tw_mobile",
        re.compile(r"\b09\d{8}\b"),
        "Taiwan mobile number",
    ),
    (
        "forum_id",
        re.compile(r"\bchengfred\b", re.I),
        "Forum/handle ID (chengfred)",
    ),
]


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    label: str
    snippet: str


def tracked_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def scan_file(rel: str) -> list[Finding]:
    path = ROOT / rel
    if not path.is_file():
        return []
    if path.suffix.lower() in SKIP_SUFFIXES:
        return []
    if rel.endswith(".dev.vars"):
        return []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    findings: list[Finding] = []
    for kind, pattern, label in PATTERNS:
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 20)
            snippet = text[start:end].replace("\n", " ").strip()
            if kind == "email" and "noreply.github.com" in snippet:
                continue
            if kind == "email" and "example.com" in snippet:
                continue
            findings.append(Finding(rel, line_no, kind, label, snippet))
    return findings


def main() -> int:
    files = tracked_files()
    all_findings: list[Finding] = []
    for rel in files:
        all_findings.extend(scan_file(rel))

    by_kind: dict[str, list[Finding]] = {}
    for f in all_findings:
        by_kind.setdefault(f.kind, []).append(f)

    print(f"Scanned {len(files)} tracked files under {ROOT}")
    print(f"Findings: {len(all_findings)}\n")

    severity_order = [
        "groq_api_key",
        "gemini_api_key",
        "openai_key",
        "bearer_secret",
        "dev_vars_real",
        "line_corpus_path",
        "ptt_corpus_path",
        "line_messages_file",
        "ptt_export_file",
        "tw_mobile",
        "email",
        "forum_id",
    ]

    exit_code = 0
    for kind in severity_order:
        items = by_kind.get(kind, [])
        if not items:
            continue
        critical = kind in {
            "groq_api_key",
            "gemini_api_key",
            "openai_key",
            "bearer_secret",
            "dev_vars_real",
            "line_corpus_path",
            "ptt_corpus_path",
            "line_messages_file",
            "ptt_export_file",
        }
        if critical:
            exit_code = 1
        print(f"## {items[0].label} ({len(items)})")
        for f in items[:30]:
            print(f"  {f.path}:{f.line}  …{f.snippet}…")
        if len(items) > 30:
            print(f"  … and {len(items) - 30} more")
        print()

    if exit_code == 0 and not all_findings:
        print("No sensitive patterns found in tracked files.")
    elif exit_code == 0:
        print("No critical secrets/corpus paths found. Review informational findings above.")
    else:
        print("CRITICAL: secrets or raw corpus references found in tracked files.")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
