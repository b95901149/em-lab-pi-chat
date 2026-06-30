#!/usr/bin/env python3
"""Build RAG chunks + search index for the web chat engine (public corpus only).

Excludes: LINE raw, PTT, board notes.
Includes: YouTube transcripts, teaching_index metadata, research summaries.

Usage:
  C:\\ProgramData\\anaconda3\\python.exe scripts/build_rag_index.py
  C:\\ProgramData\\anaconda3\\python.exe scripts/build_rag_index.py --out docs/rag
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from youtube_process_paths import COURSE_LABELS, SKILL_ROOT as _SR, TRANSCRIPTS_DIR

SKILL_ROOT = _SR

TEACHING_INDEX = SKILL_ROOT / "references/sources/youtube/teaching_index.json"
RESEARCH_INDEX = SKILL_ROOT / "references/sources/publications/research_index.json"
LINE_MESSAGES = SKILL_ROOT / "references/sources/line/chengfred_line_messages.txt"
LINE_CORPUS_MD = SKILL_ROOT / "references/research/08-line-corpus.md"
RESEARCH_MD = [
    SKILL_ROOT / "references/research/09-youtube-corpus.md",
    SKILL_ROOT / "references/research/10-lab-research-directions.md",
    SKILL_ROOT / "references/research/11-youtube-teaching-style.md",
    SKILL_ROOT / "references/research/13-research-style-publications.md",
]

CHUNK_SIZE = 600
CHUNK_OVERLAP = 80
MIN_CHUNK = 120
LINE_LITE_CHUNK = 420
LINE_LITE_OVERLAP = 50

LINE_SKIP_RE = re.compile(
    r"^(ok|OK|好|收到|嗯|？|\?|886\d+|http|www\.).*$",
    re.I,
)

LINE_SANITIZE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"鄭宇翔|郑宇翔|Yu-Hsiang\s+Cheng", re.I), "PI"),
    (re.compile(r"鄭老師|郑老师"), "PI"),
    (re.compile(r"Prof\.\s*Cheng", re.I), "PI"),
    (re.compile(r"小朋友們"), "你各位"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"Dear\s+[^:\n]{3,40}:"), "Dear 同仁:"),
    (
        re.compile(
            r"張創渝|林祈安|李奕綺|李勁|Chuang-Yu\s*Chang|"
            r"郭小姐|天任|J姊"
        ),
        "某某學長",
    ),
]

NAME_PATTERNS = [
    (re.compile(r"留學(?:就業)?分享[-－—]?\S+"), "留學分享講座"),
    (re.compile(r"鄭宇翔"), "講者"),
    (re.compile(r"Yu-Hsiang\s+Cheng", re.I), "講者"),
]


def sanitize_title(title: str) -> str:
    out = title
    for pat, repl in NAME_PATTERNS:
        out = pat.sub(repl, out)
    return out


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) <= size:
        return [text] if len(text) >= MIN_CHUNK else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if len(piece) >= MIN_CHUNK:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9][a-z0-9._-]{1,}", text):
        if len(word) >= 2:
            tokens.append(word)
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
    for i in range(len(cjk)):
        tokens.append(cjk[i])
        if i + 1 < len(cjk):
            tokens.append(cjk[i : i + 2])
    return tokens


def load_teaching_entries() -> list[dict]:
    data = json.loads(TEACHING_INDEX.read_text(encoding="utf-8"))
    return data.get("lectures") or data.get("videos") or data.get("entries") or []


def transcript_path_from_entry(entry: dict) -> Path | None:
    raw = entry.get("transcript_path") or ""
    if not raw:
        vid = entry.get("video_id")
        if not vid:
            return None
        matches = list(TRANSCRIPTS_DIR.glob(f"{vid}_*.txt"))
        return matches[0] if matches else None
    p = Path(raw.replace("\\", "/"))
    if p.is_absolute():
        return p if p.exists() else None
    candidate = SKILL_ROOT / p
    return candidate if candidate.exists() else None


def sanitize_line_text(text: str) -> str:
    out = text.strip()
    for pat, repl in LINE_SANITIZE_RULES:
        out = pat.sub(repl, out)
    return re.sub(r"\s+", " ", out).strip()


def line_message_usable(text: str) -> bool:
    if len(text) < 12:
        return False
    if LINE_SKIP_RE.match(text):
        return False
    if len(text) > 280 and sum(c.isascii() for c in text) / len(text) > 0.72:
        return False
    return True


def build_line_chunks(*, lite: bool = False) -> list[dict]:
    if not LINE_MESSAGES.exists():
        print(f"  warn: missing LINE corpus {LINE_MESSAGES}", file=sys.stderr)
        return []

    size = LINE_LITE_CHUNK if lite else 480
    overlap = LINE_LITE_OVERLAP if lite else 70
    lines = LINE_MESSAGES.read_text(encoding="utf-8", errors="replace").splitlines()
    sanitized: list[str] = []
    for raw in lines:
        text = sanitize_line_text(raw)
        if line_message_usable(text):
            sanitized.append(text)

    chunks: list[dict] = []
    cid = 0
    buffer = ""
    for msg in sanitized:
        piece = msg if not buffer else f"{buffer} / {msg}"
        if len(piece) <= size:
            buffer = piece
            continue
        if len(buffer) >= MIN_CHUNK:
            chunk_id = f"l{cid}"
            cid += 1
            chunks.append(
                {
                    "id": chunk_id,
                    "source": "line",
                    "course": "line",
                    "course_label": "LINE PI 語料",
                    "title": "實驗室 PI 發言",
                    "video_id": "",
                    "url": "",
                    "lecture_number": None,
                    "chunk_index": 0,
                    "text": buffer,
                }
            )
        tail = buffer[-overlap:] if overlap and buffer else ""
        buffer = f"{tail} / {msg}".strip(" /") if tail else msg

    if len(buffer) >= MIN_CHUNK:
        chunks.append(
            {
                "id": f"l{cid}",
                "source": "line",
                "course": "line",
                "course_label": "LINE PI 語料",
                "title": "實驗室 PI 發言",
                "video_id": "",
                "url": "",
                "lecture_number": None,
                "chunk_index": 0,
                "text": buffer,
            }
        )

    if LINE_CORPUS_MD.exists():
        summary = sanitize_line_text(
            LINE_CORPUS_MD.read_text(encoding="utf-8")[:2400]
        )
        chunks.insert(
            0,
            {
                "id": "l_meta",
                "source": "line",
                "course": "line",
                "course_label": "LINE PI 語料",
                "title": "LINE 主人格摘要",
                "video_id": "",
                "url": "",
                "lecture_number": None,
                "chunk_index": 0,
                "text": summary,
            },
        )
    return chunks


def build_transcript_chunks(entries: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    cid = 0
    for entry in entries:
        path = transcript_path_from_entry(entry)
        if not path:
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        title = sanitize_title(entry.get("title") or path.stem)
        course = entry.get("course") or "unknown"
        video_id = entry.get("video_id") or ""
        url = entry.get("url") or ""
        lecture = entry.get("lecture_number")
        for i, piece in enumerate(chunk_text(body)):
            chunk_id = f"t{cid}"
            cid += 1
            chunks.append(
                {
                    "id": chunk_id,
                    "source": "transcript",
                    "course": course,
                    "course_label": COURSE_LABELS.get(course, course),
                    "title": title,
                    "video_id": video_id,
                    "url": url,
                    "lecture_number": lecture,
                    "chunk_index": i,
                    "text": piece,
                }
            )
    return chunks


def build_research_md_chunks() -> list[dict]:
    chunks: list[dict] = []
    cid = 0
    for md_path in RESEARCH_MD:
        if not md_path.exists():
            continue
        body = md_path.read_text(encoding="utf-8")
        name = md_path.stem
        sections = re.split(r"\n(?=## )", body)
        for sec in sections:
            sec = sec.strip()
            if len(sec) < MIN_CHUNK:
                continue
            for piece in chunk_text(sec, size=800, overlap=100):
                chunk_id = f"r{cid}"
                cid += 1
                chunks.append(
                    {
                        "id": chunk_id,
                        "source": "research",
                        "course": "research",
                        "course_label": "研究與課程摘要",
                        "title": name,
                        "video_id": "",
                        "url": "",
                        "lecture_number": None,
                        "chunk_index": 0,
                        "text": piece,
                    }
                )
    return chunks


def build_research_index_chunks() -> list[dict]:
    if not RESEARCH_INDEX.exists():
        return []
    data = json.loads(RESEARCH_INDEX.read_text(encoding="utf-8"))
    chunks: list[dict] = []
    cid = 0
    taxonomy = data.get("topic_taxonomy") or []
    if isinstance(taxonomy, dict):
        items = [{"id": k, **v} if isinstance(v, dict) else {"id": k} for k, v in taxonomy.items()]
    else:
        items = taxonomy
    for topic in items:
        if not isinstance(topic, dict):
            continue
        topic_id = topic.get("id") or ""
        label = topic.get("label_zh") or topic_id
        advice = topic.get("advice") or []
        keywords = topic.get("patterns") or topic.get("keywords") or []
        text_parts = [f"主題：{label}", f"關鍵字：{', '.join(str(k) for k in keywords[:12])}"]
        text_parts.extend(f"- {a}" for a in advice)
        text = "\n".join(text_parts)
        chunk_id = f"p{cid}"
        cid += 1
        chunks.append(
            {
                "id": chunk_id,
                "source": "publications",
                "course": "research",
                "course_label": "研究選題",
                "title": label,
                "video_id": "",
                "url": "",
                "lecture_number": None,
                "chunk_index": 0,
                "text": text,
                "topic_id": topic_id,
            }
        )
    return chunks


def build_search_index(chunks: list[dict]) -> dict:
    df: Counter[str] = Counter()
    chunk_tokens: dict[str, list[str]] = {}
    for ch in chunks:
        toks = tokenize(ch["text"] + " " + ch.get("title", ""))
        chunk_tokens[ch["id"]] = toks
        df.update(set(toks))

    n = len(chunks)
    idf = {t: math.log(1 + n / (1 + c)) for t, c in df.items()}

    inverted: dict[str, list[str]] = defaultdict(list)
    for ch in chunks:
        tf = Counter(chunk_tokens[ch["id"]])
        for term in tf:
            if df[term] <= max(3, n // 10) or len(term) >= 2:
                inverted[term].append(ch["id"])

    return {
        "idf": idf,
        "inverted": {k: v for k, v in inverted.items() if len(k) >= 2},
        "chunk_count": n,
    }


def course_keywords() -> dict[str, list[str]]:
    return {
        "em": ["電磁", "maxwell", "電場", "磁場", "波動", "向量", "散度", "旋度", "poynting", "邊界"],
        "fourier_optics": ["傅立葉", "繞射", "透鏡", "4f", "角譜", "全息", "光學"],
        "fourier_optics_lab": ["光路", "michelson", "實驗", "光學元件"],
        "rf_microwave": ["微波", "天線", "smith", "傳輸線", "濾波器", "hfss", "匹配", "ghz"],
        "radio_life": ["生活", "電波", "wifi", "gps", "微波爐", "安全"],
        "research": ["thz", "太赫茲", "研究", "論文", "讀博", "lab", "實驗室", "方向"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RAG index for web chat")
    parser.add_argument("--out", type=Path, default=SKILL_ROOT / "docs" / "rag")
    parser.add_argument(
        "--lite",
        action="store_true",
        help="LINE corpus primary; skip YouTube transcripts (smaller index).",
    )
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    chunks: list[dict] = []
    chunks.extend(build_line_chunks(lite=args.lite))

    if not args.lite:
        entries = load_teaching_entries()
        chunks.extend(build_transcript_chunks(entries))
        chunks.extend(build_research_md_chunks())
        chunks.extend(build_research_index_chunks())

    search = build_search_index(chunks)
    by_course: Counter[str] = Counter(c["course"] for c in chunks)
    by_source: Counter[str] = Counter(c["source"] for c in chunks)

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "chunk_count": len(chunks),
        "by_course": dict(by_course),
        "by_source": dict(by_source),
        "primary_source": "line",
        "courses": course_keywords(),
        "sources_included": ["line_pi", "line_corpus_md"]
        + ([] if args.lite else ["youtube_transcripts", "research_md", "research_index"]),
        "sources_excluded": ["ptt", "board_notes"] + (["youtube_transcripts"] if args.lite else []),
        "lite": args.lite,
    }

    (out / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (out / "search-index.json").write_text(
        json.dumps(search, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    size_mb = (out / "chunks.json").stat().st_size / (1024 * 1024)
    print(f"Wrote {len(chunks)} chunks -> {out}")
    print(f"  chunks.json: {size_mb:.2f} MB")
    print(f"  by_source: {dict(by_source)}")
    print(f"  by_course: {dict(by_course)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
