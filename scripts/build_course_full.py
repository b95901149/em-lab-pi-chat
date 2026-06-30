#!/usr/bin/env python3
"""Build static 'chengfred YouTube Course Full' (Lite + board bundle: enhanced, index, OCR)."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_course_lite import (  # noqa: E402
    CHANNEL_NAME,
    CHANNEL_URL,
    LESSON_PLAYER_JS,
    REFERRER_META,
    SITE_JS,
    STYLE_CSS,
    build_lesson_entry,
    fmt_duration,
    transcript_preview,
)
from transcript_utils import load_segments, segment_sync_is_realtime
from youtube_process_paths import (
    COURSE_LABELS,
    COURSE_ORDER,
    WORKSPACE_ROOT,
    YOUTUBE_PROCESS_ROOT,
    lesson_dir,
    lesson_sort_key,
    manifest_by_id,
    skill_board_index_path,
)

FULL_ROOT = WORKSPACE_ROOT / "chengfred YouTube Course Full"
EM_PILOT_RE = re.compile(r"^電磁學一([1-5])\s")

BOARD_CSS = """
/* board (Full) */
.board-wrap { margin: 2rem 0 2.5rem; }
.board-wrap h2 { font-size: 1.1rem; margin-bottom: .35rem; }
.board-scene {
  margin: 1.5rem 0;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  cursor: pointer;
}
.board-scene:first-of-type { border-top: none; padding-top: 0; }
.board-head h3 { margin: 0 0 .5rem; font-size: 1rem; }
.board-head .ts { color: var(--muted); font-size: .88em; font-weight: normal; }
.board-view img {
  max-width: 100%;
  height: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  display: block;
}
.board-badge { font-size: .82rem; color: var(--muted); margin: 0 0 .35rem; }
.board-ocr-link { font-size: .92rem; margin: 1rem 0 0; }
"""

FULL_SITE_JS = SITE_JS.replace(
    'if (l.has_segments && l.realtime_sync) flags.push(\'<span class="badge">時間軸</span>\');',
    'if (l.has_board) flags.push(\'<span class="badge">板書\' + (l.board_scenes ? l.board_scenes : "") + \'</span>\');\n'
    '        if (l.has_segments && l.realtime_sync) flags.push(\'<span class="badge">時間軸</span>\');',
)

BOARD_PLAYER_JS = """
  function initBoard() {
    const wrap = document.querySelector(".board-wrap");
    if (!wrap) return;
    wrap.querySelectorAll(".board-scene").forEach((scene) => {
      scene.addEventListener("click", (e) => {
        if (e.target.closest("a")) return;
        const t = parseFloat(scene.dataset.seek || "0");
        if (typeof seekLesson === "function") seekLesson(t);
      });
    });
  }
"""

FULL_LESSON_PLAYER_JS = (
    LESSON_PLAYER_JS.replace(
        "  const origin = embedOrigin();\n  if (!origin) {\n    showFileProtocolNotice(mount);\n    initTranscript();\n    return;\n  }\n\n  const iframe = mountIframe(mount, origin);\n  bindPlayer(iframe);\n})();",
        "  const origin = embedOrigin();\n  if (!origin) {\n    showFileProtocolNotice(mount);\n    initTranscript();\n  } else {\n    const iframe = mountIframe(mount, origin);\n    bindPlayer(iframe);\n  }\n"
        + BOARD_PLAYER_JS
        + "\n  initBoard();\n})();",
    ).replace("http://localhost:8767/index.html", "http://localhost:8768/index.html")
)


def lesson_page_rel(video_id: str) -> str:
    return f"lessons/{video_id}/index.html"


def select_videos(videos: list[dict], args: argparse.Namespace) -> list[dict]:
    if args.all_with_board:
        out = []
        for v in videos:
            ld = lesson_dir(v["id"])
            if (ld / "board" / "h1080" / "enhanced").is_dir() and any(
                (ld / "board" / "h1080" / "enhanced").glob("*.png")
            ):
                out.append(v)
        return out
    if args.video_id:
        wanted = set(args.video_id)
        return [v for v in videos if v["id"] in wanted]
    if args.title_re:
        pat = re.compile(args.title_re)
        return [v for v in videos if pat.search(v.get("title") or "")]
    if args.em_pilot:
        return [v for v in videos if EM_PILOT_RE.search(v.get("title") or "")]
    return list(videos)


def copy_tree_files(src_dir: Path, dest_dir: Path, pattern: str) -> int:
    if not src_dir.is_dir():
        return 0
    dest_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for fp in sorted(src_dir.glob(pattern)):
        if fp.is_file():
            shutil.copy2(fp, dest_dir / fp.name)
            n += 1
    return n


def sync_board_bundle(video_id: str, dest_lesson: Path, title: str, course: str) -> tuple[list[dict], int]:
    """Copy enhanced PNG + OCR; return scenes for HTML and file count."""
    src_ld = lesson_dir(video_id)
    enh_src = src_ld / "board" / "h1080" / "enhanced"
    ocr_src = src_ld / "board" / "ocr"
    dest_enh = dest_lesson / "board" / "enhanced"
    dest_ocr = dest_lesson / "board" / "ocr"

    copied = copy_tree_files(enh_src, dest_enh, "*.png")
    copied += copy_tree_files(ocr_src, dest_ocr, "board_ocr*.json")
    copied += copy_tree_files(ocr_src, dest_ocr, "board_ocr*.md")

    scenes: list[dict] = []
    idx_path = skill_board_index_path(video_id)
    if idx_path.is_file():
        raw = json.loads(idx_path.read_text(encoding="utf-8"))
        for sc in raw.get("scenes") or []:
            scene_num = int(sc.get("scene") or 0)
            if scene_num <= 0:
                continue
            enh_name = f"scene_{scene_num:04d}.png"
            enh_rel = f"board/enhanced/{enh_name}"
            if not (dest_lesson / enh_rel).is_file():
                continue
            scenes.append(
                {
                    "scene": scene_num,
                    "timestamp_sec": float(sc.get("timestamp_sec") or 0),
                    "title": sc.get("title") or "",
                    "label": sc.get("label") or sc.get("title") or f"場景 {scene_num}",
                    "latex_quality": sc.get("latex_quality") or "photo_only",
                    "source_enhanced": enh_rel,
                    "ocr_text": sc.get("ocr_text") or "",
                }
            )
    else:
        ocr_jsons = sorted(ocr_src.glob("board_ocr*.json"), key=lambda p: ("full" not in p.name, p.name))
        frames: list[dict] = []
        for fp in reversed(ocr_jsons):
            data = json.loads(fp.read_text(encoding="utf-8"))
            frames = data.get("frames") or []
            if frames:
                break
        for i, fr in enumerate(frames, start=1):
            enh_name = f"scene_{i:04d}.png"
            enh_rel = f"board/enhanced/{enh_name}"
            if not (dest_lesson / enh_rel).is_file():
                continue
            scenes.append(
                {
                    "scene": i,
                    "timestamp_sec": float(fr.get("timestamp_sec") or fr.get("time_sec") or 0),
                    "title": fr.get("title") or f"場景 {i}",
                    "label": fr.get("label") or f"場景 {i}",
                    "latex_quality": "photo_only",
                    "source_enhanced": enh_rel,
                    "ocr_text": fr.get("ocr_text") or "",
                }
            )

    scenes.sort(key=lambda s: (s.get("timestamp_sec", 0), s.get("scene", 0)))
    board_index = {
        "video_id": video_id,
        "title": title,
        "course": course,
        "course_label": COURSE_LABELS.get(course, course),
        "bundle": "enhanced+index+ocr",
        "scenes": scenes,
    }
    (dest_lesson / "board_index.json").write_text(
        json.dumps(board_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    copied += 1
    return scenes, copied


def render_board_section(scenes: list[dict]) -> str:
    if not scenes:
        return ""
    blocks: list[str] = []
    for sc in scenes:
        ts = int(sc.get("timestamp_sec") or 0)
        label = html.escape(sc.get("label") or sc.get("title") or f"場景 {sc.get('scene', '?')}")
        photo = sc.get("source_enhanced")
        if not photo:
            continue
        block = f'<section class="board-scene" data-seek="{ts}">'
        block += f'<div class="board-head"><h3>{label} <span class="ts">{ts}s</span></h3></div>'
        block += (
            f'<div class="board-view">'
            f'<p class="board-badge">板書原圖（點擊跳轉影片）</p>'
            f'<img src="{html.escape(photo)}" alt="{label}" loading="lazy"/>'
            f"</div></section>"
        )
        blocks.append(block)
    if not blocks:
        return ""
    return (
        '<section class="board-wrap"><h2>板書</h2>'
        '<p class="muted">含 OCR 強化圖；點任一板書可跳轉 YouTube 至對應時間。</p>'
        + "".join(blocks)
        + "</section>"
    )


def render_lesson_page(entry: dict, segments: list[dict], scenes: list[dict], has_ocr_md: bool) -> str:
    vid = entry["video_id"]
    seg_json = json.dumps(segments, ensure_ascii=False) if segments else "[]"
    transcript_section = ""
    if segments:
        transcript_section = f"""
  <section class="transcript-wrap">
    <h2>逐字稿 <span class="hint">（點段落可跳轉影片；播放時自動跟隨）</span></h2>
    <div id="transcript-viewport" class="transcript-viewport">
      <div id="transcript-track"></div>
    </div>
    <script id="segments-data" type="application/json">{seg_json}</script>
  </section>"""
    elif entry["has_transcript"]:
        transcript_section = """
  <section class="transcript-wrap">
    <h2>逐字稿</h2>
    <p class="meta">已有逐字稿文字，尚無時間軸標記。</p>
  </section>"""

    board_html = render_board_section(scenes)
    ocr_link = ""
    if has_ocr_md:
        ocr_link = '<p class="board-ocr-link"><a href="board/ocr/board_ocr_1080p_full.md">OCR 全文（Markdown）</a></p>'

    subtitle_bar = ""
    if segments:
        subtitle_bar = (
            '<div id="subtitle-bar" class="subtitle-bar" aria-live="polite">'
            '<span class="subtitle-time">0:00</span>'
            '<span class="subtitle-text">—</span></div>'
        )

    sync_notice = ""
    if segments and not entry.get("realtime_sync"):
        sync_notice = (
            '<p class="notice-sync">字幕尚未即時同步：時間軸依逐字稿字數估算，'
            "點擊跳轉可能略有偏差。</p>"
        )

    board_notice = ""
    if not scenes:
        board_notice = '<p class="notice-sync">此講次尚無板書資料（需先執行板書擷取流程）。</p>'

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  {REFERRER_META}
  <title>{html.escape(entry["title"])} — {CHANNEL_NAME}</title>
  <link rel="stylesheet" href="../../assets/style.css"/>
</head>
<body>
  <div class="wrap">
    <p class="nav-top"><a href="../../index.html">← 課程總覽</a></p>
    <div class="lesson-hero">
      <h1>{html.escape(entry["title"])}</h1>
      <p class="meta">{html.escape(entry["course_label"])} · {entry["duration"]} · ID <code>{html.escape(vid)}</code></p>
      <p class="meta"><a href="{html.escape(entry["url"])}" target="_blank" rel="noopener">在 YouTube 開啟</a></p>
    </div>
    <section class="player-stack">
      <div class="yt-wrap"><div id="yt-player-mount"></div></div>
      {subtitle_bar}
    </section>
    <p class="notice">逐字稿由語音辨識自動生成，尚未人工校正。板書為 OCR 強化圖（enhanced + index + OCR）。</p>
    {sync_notice}
    {board_notice}
    {board_html}
    {ocr_link}
    {transcript_section}
  </div>
  <script>window.LESSON_CONFIG = {{ videoId: {json.dumps(vid)} }};</script>
  <script src="../../assets/lesson-player.js"></script>
</body>
</html>
"""


def render_index(catalog: dict) -> str:
    cat_json = json.dumps(catalog, ensure_ascii=False)
    stats = catalog["stats"]
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  {REFERRER_META}
  <title>{CHANNEL_NAME} — 課程索引 Full</title>
  <link rel="stylesheet" href="assets/style.css"/>
</head>
<body>
  <header class="hero">
    <div class="wrap">
      <h1>{CHANNEL_NAME} 課程索引 <span style="font-size:.75em;font-weight:600;opacity:.9">Full</span></h1>
      <p>YouTube 嵌入 · 同步逐字稿 · 板書（enhanced + OCR）</p>
      <p class="links"><a href="{CHANNEL_URL}" target="_blank" rel="noopener">YouTube 頻道</a></p>
      <div class="stats">
        <span class="stat">共 {stats["total"]} 支影片</span>
        <span class="stat">{stats["with_board"]} 支含板書</span>
        <span class="stat">{stats["with_transcript"]} 支含逐字稿</span>
        <span class="stat">{stats["board_files"]} 個板書檔案</span>
      </div>
    </div>
  </header>
  <main class="wrap">
    <p class="notice">備註：Full 版含板書強化圖與 OCR，不含本機 MP4。本機預覽請執行 <code>serve.bat</code>（port 8768）。</p>
    <div class="toolbar">
      <input id="search" type="search" placeholder="搜尋講次標題、關鍵字…" autocomplete="off"/>
      <span id="result-count" class="meta"></span>
    </div>
    <div id="course-filters" class="filters"></div>
    <div id="course-sections"></div>
    <p class="foot">產生時間：{html.escape(catalog["generated"])} · Full 靜態版 · {html.escape(catalog.get("build_note", ""))}</p>
  </main>
  <script id="catalog-data" type="application/json">{cat_json}</script>
  <script src="assets/site.js"></script>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build chengfred YouTube Course Full static site")
    parser.add_argument("--video-id", action="append", default=[], help="Include specific video id (repeatable)")
    parser.add_argument("--title-re", default="", help="Include videos whose title matches this regex")
    parser.add_argument(
        "--em-pilot",
        action="store_true",
        default=False,
        help="Include 電磁學一 1–5 only (default when no other filter)",
    )
    parser.add_argument("--all-with-board", action="store_true", help="All manifest videos that have board enhanced PNGs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.video_id and not args.title_re and not args.all_with_board:
        args.em_pilot = True

    all_videos = list(manifest_by_id().values())
    targets = select_videos(all_videos, args)
    if not targets:
        print("No videos matched the selection.", file=sys.stderr)
        return 1

    targets.sort(key=lambda v: (v.get("course", ""), lesson_sort_key(v.get("title") or "", v.get("course") or "")))

    assets_dir = FULL_ROOT / "assets"
    lessons_root = FULL_ROOT / "lessons"
    assets_dir.mkdir(parents=True, exist_ok=True)
    lessons_root.mkdir(parents=True, exist_ok=True)

    (assets_dir / "style.css").write_text(STYLE_CSS + BOARD_CSS, encoding="utf-8")
    (assets_dir / "site.js").write_text(FULL_SITE_JS, encoding="utf-8")
    (assets_dir / "lesson-player.js").write_text(FULL_LESSON_PLAYER_JS, encoding="utf-8")

    lessons: list[dict] = []
    board_files = 0
    with_board = 0
    with_transcript = 0
    with_segments = 0

    for v in targets:
        vid = v["id"]
        entry = build_lesson_entry(v)
        entry["page"] = lesson_page_rel(vid)
        entry["has_board"] = False
        entry["board_scenes"] = 0

        dest = lessons_root / vid
        dest.mkdir(parents=True, exist_ok=True)

        scenes, copied = sync_board_bundle(vid, dest, v.get("title") or vid, v.get("course") or "other")
        board_files += copied
        if scenes:
            entry["has_board"] = True
            entry["board_scenes"] = len(scenes)
            with_board += 1

        has_ocr_md = (dest / "board" / "ocr" / "board_ocr_1080p_full.md").is_file()
        segments = load_segments(vid, v.get("duration"))
        if entry["has_transcript"]:
            with_transcript += 1
        if segments:
            with_segments += 1

        page_path = dest / "index.html"
        page_path.write_text(render_lesson_page(entry, segments, scenes, has_ocr_md), encoding="utf-8")
        lessons.append(entry)

    build_note = "電磁學一 1–5 試跑" if args.em_pilot and not args.video_id else (
        "全部已建板書講次（--all-with-board）" if args.all_with_board else "自訂篩選"
    )
    catalog = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "channel_url": CHANNEL_URL,
        "channel_name": CHANNEL_NAME,
        "course_order": COURSE_ORDER,
        "course_labels": COURSE_LABELS,
        "build_note": build_note,
        "stats": {
            "total": len(lessons),
            "with_board": with_board,
            "with_transcript": with_transcript,
            "with_segments": with_segments,
            "board_files": board_files,
            "courses": len({l["course"] for l in lessons if l["course"] in COURSE_ORDER}),
        },
        "lessons": lessons,
    }

    (FULL_ROOT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    (FULL_ROOT / "index.html").write_text(render_index(catalog), encoding="utf-8")

    serve_script = SCRIPTS / "serve_course_full.py"
    (FULL_ROOT / "serve.bat").write_text(
        "@echo off\n"
        f'cd /d "{FULL_ROOT}"\n'
        f'C:\\ProgramData\\anaconda3\\python.exe "{serve_script}"\n',
        encoding="utf-8",
    )
    (FULL_ROOT / ".htaccess").write_text(
        "<IfModule mod_headers.c>\n"
        '  Header always set Referrer-Policy "strict-origin-when-cross-origin"\n'
        "</IfModule>\n",
        encoding="utf-8",
    )
    (FULL_ROOT / "_headers").write_text(
        "/*\n  Referrer-Policy: strict-origin-when-cross-origin\n",
        encoding="utf-8",
    )

    total_mb = sum(f.stat().st_size for f in FULL_ROOT.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"Wrote {FULL_ROOT}")
    print(f"  lessons: {len(lessons)}")
    print(f"  with board: {with_board}")
    print(f"  board files copied: {board_files}")
    print(f"  site size: {total_mb:.1f} MB")
    print(f"  source: {YOUTUBE_PROCESS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
