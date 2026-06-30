"""Load domain glossaries and build ASR correction replacement pairs."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

GLOSSARY_DIR = Path(__file__).resolve().parents[1] / "references" / "glossary"
INDEX_PATH = GLOSSARY_DIR / "index.json"

# Pairs to skip when wrong==right would be no-op, or known risky global replaces.
SKIP_WRONG = frozenset(
    {
        "通量",  # aliases_wrong includes correct form
        "caution: 負數語境勿替換",
        "caution: 分配率有時指 ratio",
        "unit vector 聽寫錯誤",
        "basis vector",
    }
)


@lru_cache(maxsize=1)
def load_glossary_index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def load_glossary(glossary_id: str) -> dict:
    index = load_glossary_index()
    rel = index["files"][glossary_id]
    return json.loads((GLOSSARY_DIR / rel).read_text(encoding="utf-8"))


def glossary_ids_for_course(course: str) -> list[str]:
    index = load_glossary_index()
    entry = index.get("courses", {}).get(course)
    if entry:
        return list(entry.get("glossaries") or [])
    return list(index.get("default_glossaries") or [])


def whisper_prompt_for_course(course: str) -> str | None:
    index = load_glossary_index()
    key = f"combined_whisper_prompt_{course}"
    return index.get(key)


def _is_usable_wrong(token: str) -> bool:
    if not token or token in SKIP_WRONG:
        return False
    if token.startswith("caution:"):
        return False
    if re.fullmatch(r"[A-Za-z0-9\s\-]+", token) and len(token) > 20:
        return False
    return True


def build_replacement_pairs(
    glossary_ids: list[str] | None = None,
    *,
    course: str | None = "em",
    skip_cautious: bool = False,
) -> list[tuple[str, str]]:
    """Return (wrong, right) pairs sorted longest-first for greedy replace."""
    if glossary_ids is None:
        if not course:
            raise ValueError("glossary_ids or course required")
        glossary_ids = glossary_ids_for_course(course)

    pairs: dict[str, str] = {}
    cautious_wrong: set[str] = set()

    for gid in glossary_ids:
        data = load_glossary(gid)
        for item in data.get("asr_corrections") or []:
            right = (item.get("right") or "").strip()
            if not right:
                continue
            if item.get("caution") and skip_cautious:
                wrong = (item.get("wrong") or "").strip()
                if wrong:
                    cautious_wrong.add(wrong)
                for alias in item.get("aliases_wrong") or []:
                    cautious_wrong.add(str(alias).strip())
                continue

            wrong = (item.get("wrong") or "").strip()
            if wrong and wrong != right and _is_usable_wrong(wrong):
                pairs[wrong] = right

            for alias in item.get("aliases_wrong") or []:
                alias = str(alias).strip()
                if alias and alias != right and _is_usable_wrong(alias):
                    pairs[alias] = right

    for w in cautious_wrong:
        pairs.pop(w, None)

    return sorted(pairs.items(), key=lambda x: len(x[0]), reverse=True)


def apply_corrections(text: str, pairs: list[tuple[str, str]]) -> tuple[str, dict[str, int]]:
    """Apply replacements; return new text and per-rule hit counts."""
    counts: dict[str, int] = {}
    out = text
    for wrong, right in pairs:
        if wrong not in out:
            continue
        n = out.count(wrong)
        if n:
            counts[f"{wrong}→{right}"] = n
            out = out.replace(wrong, right)
    return out, counts
