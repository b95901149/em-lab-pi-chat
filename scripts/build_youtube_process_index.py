#!/usr/bin/env python3
"""Build YouTubeProcess index.html + per-lesson pages + catalog.json."""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from transcript_utils import find_skill_transcript, load_segments, segment_sync_is_realtime, sync_all_transcripts
from youtube_process_paths import (
    BOARD_NOTES_DIR,
    COURSE_LABELS,
    COURSE_ORDER,
    MANIFEST_PATH,
    SKILL_ROOT,
    YOUTUBE_PROCESS_ROOT,
    board_ocr_dir,
    lesson_dir,
    lesson_sort_key,
    manifest_by_id,
    relpath_from,
    skill_board_index_path,
    skill_latex_dir,
    video_path,
    write_lesson_meta,
)


PLAYER_SEEK_JS = """
<script>
window.seekPlayer = window.seekPlayer || function(player, sec) {
  if (!player || !Number.isFinite(sec)) return;
  const target = Math.max(0, sec);
  const run = () => {
    try {
      if (player.seekable && player.seekable.length > 0) {
        const end = player.seekable.end(player.seekable.length - 1);
        player.currentTime = Math.min(target, end);
      } else {
        player.currentTime = target;
      }
      player.play().catch(() => {});
    } catch (e) {}
  };
  if (player.readyState >= 1) run();
  else player.addEventListener("loadedmetadata", run, { once: true });
};
</script>"""


def fmt_duration(sec: float | None) -> str:
    if not sec:
        return "—"
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def load_board_scenes(video_id: str) -> list[dict]:
    idx = skill_board_index_path(video_id)
    if not idx.is_file():
        return []
    data = json.loads(idx.read_text(encoding="utf-8"))
    return data.get("scenes") or []


def load_board_ocr_frames(video_id: str) -> list[dict]:
    ocr_dir = board_ocr_dir(video_id)
    if not ocr_dir.is_dir():
        return []
    candidates = sorted(ocr_dir.glob("board_ocr*.json"), key=lambda p: ("full" not in p.name, p.name))
    for fp in reversed(candidates):
        data = json.loads(fp.read_text(encoding="utf-8"))
        frames = data.get("frames") or []
        if frames:
            return frames
    return []


def board_image_href(lesson_dir_path: Path, rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    target = YOUTUBE_PROCESS_ROOT / Path(rel_path.replace("\\", "/"))
    if not target.is_file():
        return None
    return relpath_from(lesson_dir_path, target)


def render_board_section(scenes: list[dict], lesson_dir_path: Path) -> str:
    if not scenes:
        return ""
    has_toggle = any(
        board_image_href(lesson_dir_path, sc.get("source_enhanced"))
        or board_image_href(lesson_dir_path, sc.get("source_crop"))
        for sc in scenes
    )
    blocks: list[str] = []
    for sc in scenes:
        ts = int(sc.get("timestamp_sec") or 0)
        scene_id = sc.get("scene", "?")
        label = html.escape(sc.get("label") or sc.get("title") or f"場景 {scene_id}")
        quality = sc.get("latex_quality") or ("template" if sc.get("png") else "photo_only")
        latex_png = skill_asset_href(lesson_dir_path, sc.get("png")) if quality != "photo_only" else None
        if not latex_png and sc.get("png") and quality != "photo_only":
            latex_png = skill_asset_href(lesson_dir_path, sc.get("png"))
        tex_href = skill_asset_href(lesson_dir_path, sc.get("tex"))
        photo = board_image_href(lesson_dir_path, sc.get("source_enhanced")) or board_image_href(
            lesson_dir_path, sc.get("source_crop")
        )
        has_real_latex = quality in ("template", "pix2tex") and latex_png

        block = f'<section class="board-scene" data-seek="{ts}">'
        block += '<div class="board-head">'
        block += f"<h3>{label} <span class=\"ts\">{ts}s</span></h3>"
        block += "</div>"

        if has_real_latex:
            block += (
                f'<div class="board-view board-latex">'
                f'<img src="{html.escape(latex_png)}" alt="{label}" loading="lazy"/>'
            )
            if tex_href:
                block += f'<p class="tex-link"><a href="{html.escape(tex_href)}">LaTeX 源碼</a></p>'
            block += "</div>"
        elif photo:
            block += (
                f'<div class="board-view board-latex board-fallback">'
                f'<p class="board-badge">原圖（此場景無合格 LaTeX）</p>'
                f'<img src="{html.escape(photo)}" alt="{label}" loading="lazy"/>'
                "</div>"
            )

        if photo and has_real_latex:
            block += (
                f'<div class="board-view board-photo hidden">'
                f'<img src="{html.escape(photo)}" alt="{label} 原圖" loading="lazy"/>'
                "</div>"
            )
        elif photo and not has_real_latex:
            block += (
                f'<div class="board-view board-photo hidden">'
                f'<img src="{html.escape(photo)}" alt="{label} 原圖" loading="lazy"/>'
                "</div>"
            )

        if not has_real_latex and not photo:
            block += '<p class="muted">（尚無板書圖檔）</p>'
        block += "</section>"
        blocks.append(block)

    global_toggle = ""
    if has_toggle:
        global_toggle = """
  <div class="board-global-bar">
    <span class="board-global-label">全部板書顯示：</span>
    <div class="board-global-toggle" role="group" aria-label="全部板書顯示模式">
      <button type="button" class="global-toggle-btn active" data-view="latex">LaTeX</button>
      <button type="button" class="global-toggle-btn" data-view="photo">原圖</button>
    </div>
  </div>"""

    board_js = """
<script>
(function() {
  const player = document.getElementById("player");
  const wrap = document.querySelector(".board-wrap");
  if (!wrap) return;

  function setBoardView(view) {
    wrap.querySelectorAll(".board-scene").forEach((scene) => {
      const latex = scene.querySelector(".board-latex");
      const photo = scene.querySelector(".board-photo");
      if (latex) latex.classList.toggle("hidden", view !== "latex");
      if (photo) photo.classList.toggle("hidden", view !== "photo");
    });
    wrap.querySelectorAll(".global-toggle-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === view);
    });
  }

  wrap.querySelectorAll(".global-toggle-btn").forEach((btn) => {
    btn.addEventListener("click", () => setBoardView(btn.dataset.view));
  });

  wrap.querySelectorAll(".board-scene").forEach((scene) => {
    scene.addEventListener("click", (e) => {
      if (e.target.closest("a, button")) return;
      if (!player) return;
      const t = parseFloat(scene.dataset.seek || "0");
      window.seekPlayer(player, t);
    });
    if (player) scene.style.cursor = "pointer";
  });
})();
</script>"""
    return (
        f'<section class="board-wrap"><h2>板書</h2>'
        f'{global_toggle}'
        f'<p class="muted">LaTeX 僅顯示人工模板或高信心公式；其餘場景在 LaTeX 模式亦顯示原圖。點板書可跳轉影片。</p>'
        + "".join(blocks)
        + board_js
        + "</section>"
    )


def lesson_status(video_id: str) -> dict:
    v = manifest_by_id()[video_id]
    ld = lesson_dir(video_id)
    has_video = video_path(video_id).is_file()
    has_board_ocr = (ld / "board" / "ocr").exists() and any((ld / "board" / "ocr").glob("board_ocr*.json"))
    scenes = load_board_scenes(video_id)
    ocr_frames = load_board_ocr_frames(video_id)
    has_latex = bool(scenes) or skill_latex_dir(video_id).exists()
    has_transcript = find_skill_transcript(video_id) is not None
    segments = load_segments(video_id, v.get("duration"))
    has_segments = bool(segments)
    return {
        "video_id": video_id,
        "title": v["title"],
        "course": v["course"],
        "course_label": COURSE_LABELS.get(v["course"], v["course"]),
        "url": v["url"],
        "duration_sec": v.get("duration"),
        "duration": fmt_duration(v.get("duration")),
        "lesson_path": ld.relative_to(YOUTUBE_PROCESS_ROOT).as_posix() if ld.exists() else None,
        "has_video": has_video,
        "has_board_ocr": has_board_ocr,
        "has_latex": has_latex,
        "has_transcript": has_transcript,
        "has_segments": has_segments,
        "realtime_sync": segment_sync_is_realtime(video_id) if has_segments else False,
        "ocr_frame_count": len(ocr_frames),
        "segments": segments,
        "scenes": scenes,
        "ocr_frames": ocr_frames,
    }


def skill_asset_href(from_dir: Path, skill_rel_path: str | None) -> str | None:
    if not skill_rel_path:
        return None
    target = SKILL_ROOT / Path(skill_rel_path.replace("\\", "/"))
    if not target.is_file():
        return None
    return relpath_from(from_dir, target)


def render_transcript_block(item: dict, with_subtitle: bool = False) -> str:
    segments = item.get("segments") or []
    if not segments:
        if item.get("has_transcript"):
            return '<section class="transcript-wrap"><h2>逐字稿</h2><p class="muted">逐字稿已建立，尚無時間標記（之後 ASR 會自動產生 segments）。</p></section>'
        return ""

    seg_json = json.dumps(segments, ensure_ascii=False)
    subtitle_init = ""
    if with_subtitle:
        subtitle_init = """
  const subtitleBar = document.getElementById("subtitle-bar");
  function updateSubtitle(idx) {
    if (!subtitleBar || idx < 0) return;
    const seg = segments[idx];
    subtitleBar.querySelector(".subtitle-time").textContent = fmt(seg.start);
    subtitleBar.querySelector(".subtitle-text").textContent = seg.text;
  }"""
    else:
        subtitle_init = """
  function updateSubtitle(_idx) {}"""

    return f"""<section class="transcript-wrap">
  <h2>逐字稿 <span class="hint">（可捲動瀏覽；點段落跳轉；播放時自動跟隨）</span></h2>
  <div id="transcript-viewport" class="transcript-viewport">
    <div id="transcript-track" class="transcript-track"></div>
  </div>
  <script id="segments-data" type="application/json">{seg_json}</script>
  <script>
(function() {{
  const player = document.getElementById("player");
  const dataEl = document.getElementById("segments-data");
  if (!dataEl) return;
  const segments = JSON.parse(dataEl.textContent);
  const viewport = document.getElementById("transcript-viewport");
  const track = document.getElementById("transcript-track");
  if (!track || !segments.length) return;

  function fmt(sec) {{
    const s = Math.floor(sec % 60).toString().padStart(2, "0");
    const m = Math.floor(sec / 60);
    return m + ":" + s;
  }}
{subtitle_init}

  let activeIdx = -1;
  let autoScroll = true;
  let scrollPauseTimer = null;

  function pauseAutoScroll() {{
    autoScroll = false;
    clearTimeout(scrollPauseTimer);
    scrollPauseTimer = setTimeout(() => {{ autoScroll = true; }}, 5000);
  }}

  if (viewport) {{
    viewport.addEventListener("wheel", pauseAutoScroll, {{ passive: true }});
    viewport.addEventListener("mousedown", pauseAutoScroll);
    viewport.addEventListener("touchstart", pauseAutoScroll, {{ passive: true }});
  }}

  segments.forEach((seg, i) => {{
    const div = document.createElement("div");
    div.className = "seg";
    div.dataset.idx = String(i);
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = fmt(seg.start);
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = seg.text;
    div.appendChild(time);
    div.appendChild(text);
    div.addEventListener("click", () => {{
      autoScroll = true;
      clearTimeout(scrollPauseTimer);
      if (player) window.seekPlayer(player, seg.start);
    }});
    track.appendChild(div);
  }});

  function findActive(t) {{
    for (let i = 0; i < segments.length; i++) {{
      const s = segments[i];
      if (t >= s.start && t < s.end) return i;
    }}
    if (t < segments[0].start) return 0;
    return segments.length - 1;
  }}

  function scrollToSegment(idx) {{
    const el = track.children[idx];
    if (!el || !viewport || !autoScroll) return;
    const elTop = el.offsetTop;
    const elH = el.offsetHeight;
    const vh = viewport.clientHeight;
    const target = elTop - vh / 2 + elH / 2;
    const maxScroll = viewport.scrollHeight - vh;
    const clamped = Math.max(0, Math.min(target, maxScroll));
    viewport.scrollTo({{ top: clamped, behavior: "smooth" }});
  }}

  function setActive(idx) {{
    if (idx < 0) return;
    const changed = idx !== activeIdx;
    activeIdx = idx;
    const children = track.children;
    for (let i = 0; i < children.length; i++) {{
      children[i].classList.toggle("active", i === idx);
    }}
    if (changed) {{
      updateSubtitle(idx);
      scrollToSegment(idx);
    }}
  }}

  function syncFromPlayer() {{
    if (!player) return;
    setActive(findActive(player.currentTime));
  }}

  if (player) {{
    player.addEventListener("timeupdate", syncFromPlayer);
    player.addEventListener("seeked", syncFromPlayer);
    syncFromPlayer();
  }} else {{
    setActive(0);
  }}

  window.addEventListener("resize", () => scrollToSegment(activeIdx));
}})();
  </script>
</section>"""


def render_video_block(local_href: str | None, with_subtitle: bool = False) -> str:
    if not local_href:
        return ""
    subtitle_html = ""
    if with_subtitle:
        subtitle_html = """
  <div id="subtitle-bar" class="subtitle-bar" aria-live="polite">
    <span class="subtitle-time">0:00</span>
    <span class="subtitle-text">—</span>
  </div>"""
    return f"""<section class="video-wrap">
  <div class="player-stack">
  <video id="player" controls preload="auto" playsinline src="{html.escape(local_href)}">
    您的瀏覽器不支援 HTML5 影片播放。
  </video>{subtitle_html}
  </div>
</section>"""


def render_lesson_page(item: dict, lesson_dir_path: Path) -> str:
    vid = item["video_id"]
    local_video = video_path(vid)
    local_href = "video_1080p.mp4" if local_video.is_file() else None
    board_html = render_board_section(item.get("scenes") or [], lesson_dir_path)
    if not board_html and item.get("ocr_frames"):
        board_html = '<section class="board-wrap"><h2>板書</h2><p class="muted">OCR 已擷取，請執行 board_to_latex.py --all 產生 LaTeX。</p></section>'
    elif not board_html:
        board_html = "<p>尚無板書資料（請執行 extract_board_frames.py）。</p>"

    ocr_link = ""
    ocr_md = lesson_dir_path / "board" / "ocr" / "board_ocr_1080p_full.md"
    if ocr_md.is_file():
        ocr_link = '<p><a href="board/ocr/board_ocr_1080p_full.md">OCR 全文（原始）</a></p>'

    local_link = ""
    if local_href:
        local_link = f' · <a href="{html.escape(local_href)}">下載 MP4</a>'

    has_segments = bool(item.get("segments"))
    video_block = render_video_block(local_href, with_subtitle=has_segments)
    player_seek_js = PLAYER_SEEK_JS if local_href else ""
    transcript_block = render_transcript_block(item, with_subtitle=has_segments)
    sync_notice = ""
    if has_segments and not item.get("realtime_sync"):
        sync_notice = (
            '<p class="notice-sync">字幕尚未即時同步：時間軸依逐字稿字數估算，'
            "點擊跳轉可能略有偏差；板書擷取流程完成後會改為 Whisper 精準對齊。</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(item["title"])} — 鄭宇翔 YouTube</title>
  <style>
    body {{ font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; margin: 2rem auto; max-width: 900px; padding: 0 1rem; line-height: 1.5; }}
    a {{ color: #0b57d0; }}
    .meta {{ color: #555; margin-bottom: 1.5rem; }}
    .video-wrap {{ margin: 1.5rem 0; }}
    .player-stack {{ border-radius: 6px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.12); }}
    .player-stack video {{ display: block; width: 100%; max-width: 100%; background: #000; }}
    .subtitle-bar {{
      display: flex; align-items: flex-start; gap: 0.75rem;
      min-height: 3.2rem; padding: 0.7rem 1rem;
      background: #1e1e1e; color: #f5f5f5;
      border-top: 1px solid #333;
    }}
    .subtitle-bar .subtitle-time {{
      flex-shrink: 0; color: #9aa0a6; font-size: 0.85em;
      font-variant-numeric: tabular-nums; padding-top: 0.1rem;
    }}
    .subtitle-bar .subtitle-text {{ flex: 1; line-height: 1.45; font-size: 1.05rem; }}
    .transcript-wrap {{ margin: 2rem 0; }}
    .transcript-wrap .hint {{ font-size: 0.85em; font-weight: normal; color: #888; }}
    .transcript-viewport {{
      height: 14rem; overflow-y: auto; overflow-x: hidden;
      border: 1px solid #e0e0e0; border-radius: 6px;
      background: #fafafa; position: relative;
      scrollbar-gutter: stable;
    }}
    .transcript-track {{
      padding: 0.25rem 0;
    }}
    .seg {{ padding: 0.4rem 0.75rem; cursor: pointer; border-left: 3px solid transparent; }}
    .seg:hover {{ background: #f0f0f0; }}
    .seg.active {{ background: #fff8e1; border-left-color: #f9a825; }}
    .seg .time {{ color: #888; font-size: 0.85em; margin-right: 0.6rem; font-variant-numeric: tabular-nums; }}
    .muted {{ color: #666; }}
    .board-wrap {{ margin: 2.5rem 0; }}
    .board-global-bar {{
      display: flex; align-items: center; flex-wrap: wrap; gap: 0.6rem;
      margin: 0.75rem 0 1rem; padding: 0.55rem 0.75rem;
      background: #f5f7fa; border: 1px solid #e0e4ea; border-radius: 6px;
    }}
    .board-global-label {{ font-size: 0.92rem; color: #444; }}
    .board-global-toggle {{ display: flex; gap: 0.25rem; }}
    .global-toggle-btn, .toggle-btn {{
      border: 1px solid #ccc; background: #fff; padding: 0.3rem 0.85rem;
      border-radius: 4px; cursor: pointer; font-size: 0.88rem;
    }}
    .global-toggle-btn.active, .toggle-btn.active {{
      background: #e8f0fe; border-color: #0b57d0; color: #0b57d0; font-weight: 600;
    }}
    .board-scene {{ margin: 2rem 0; padding-top: 1rem; border-top: 1px solid #ddd; }}
    .board-head {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.5rem; }}
    .board-head h3 {{ margin: 0; }}
    .board-view img {{ max-width: 100%; height: auto; border: 1px solid #eee; display: block; margin: 0.5rem 0; background: #fff; }}
    .board-view.hidden {{ display: none; }}
    .board-badge {{ font-size: 0.82rem; color: #666; margin: 0 0 0.35rem; }}
    .board-fallback img {{ border-style: dashed; }}
    .tex-link {{ font-size: 0.9rem; margin: 0.25rem 0 0; }}
    .scene {{ margin: 2rem 0; padding-top: 1rem; border-top: 1px solid #ddd; }}
    .scene img {{ max-width: 100%; height: auto; border: 1px solid #eee; }}
    .ts {{ color: #888; font-size: 0.9em; font-weight: normal; }}
    nav {{ margin-bottom: 2rem; }}
    .notice-sync {{
      margin: 1rem 0; padding: 0.7rem 0.9rem;
      background: #fff3e0; border-left: 4px solid #fb8c00;
      border-radius: 4px; color: #5d4037; font-size: 0.92rem;
    }}
  </style>
</head>
<body>
  <nav><a href="../../../index.html">← 課程總覽</a></nav>
  <h1>{html.escape(item["title"])}</h1>
  <p class="meta">{html.escape(item["course_label"])} · {item["duration"]} · ID <code>{html.escape(vid)}</code></p>
  <p>
    <a href="{html.escape(item["url"])}" target="_blank" rel="noopener">在 YouTube 觀看</a>{local_link}
  </p>
  {video_block}
  {sync_notice}
  {player_seek_js}
  {transcript_block}
  {ocr_link}
  {board_html}
</body>
</html>
"""


def render_index(catalog: dict) -> str:
    sections = []
    for course in COURSE_ORDER:
        lessons = [x for x in catalog["lessons"] if x["course"] == course]
        lessons.sort(key=lambda x: lesson_sort_key(x.get("title") or "", x.get("course") or ""))
        if not lessons:
            continue
        rows = []
        for it in lessons:
            flags = []
            if it["has_video"]:
                flags.append("影片")
            if it.get("ocr_frame_count"):
                flags.append(f"板書{it['ocr_frame_count']}")
            elif it["has_board_ocr"]:
                flags.append("OCR")
            if it["has_latex"]:
                flags.append("板書")
            if it.get("has_transcript"):
                flags.append("逐字稿")
            if it.get("has_segments"):
                if it.get("realtime_sync"):
                    flags.append("時間軸")
                else:
                    flags.append("字幕尚未即時同步")
            flag_txt = " · ".join(flags) if flags else "—"
            if it.get("lesson_page"):
                title_cell = f'<a href="{html.escape(it["lesson_page"])}">{html.escape(it["title"])}</a>'
            else:
                title_cell = html.escape(it["title"])
            rows.append(
                f'<tr><td>{title_cell}</td>'
                f'<td>{it["duration"]}</td><td>{flag_txt}</td>'
                f'<td><a href="{html.escape(it["url"])}" target="_blank" rel="noopener">YouTube</a></td></tr>'
            )
        sections.append(
            f"<section><h2>{html.escape(COURSE_LABELS.get(course, course))}</h2>"
            f'<table><thead><tr><th>標題</th><th>長度</th><th>資料</th><th>連結</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></section>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>鄭宇翔 YouTube 課程索引</title>
  <style>
    body {{ font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; margin: 2rem auto; max-width: 960px; padding: 0 1rem; }}
    h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3rem; }}
    section {{ margin: 2.5rem 0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid #e0e0e0; }}
    th {{ background: #f5f5f5; }}
    a {{ color: #0b57d0; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .foot {{ color: #666; font-size: 0.9rem; margin-top: 3rem; }}
    .notice {{
      margin: 1rem 0 2rem; padding: 0.75rem 1rem;
      background: #fff8e1; border-left: 4px solid #f9a825;
      color: #5f4339; font-size: 0.95rem;
    }}
  </style>
</head>
<body>
  <h1>鄭宇翔 YouTube 課程索引</h1>
  <p>點選課程標題進入該講頁面：內嵌影片、同步逐字稿、板書 LaTeX 圖與 YouTube 連結。</p>
  <p class="notice">備註：逐字稿由語音辨識自動生成，尚未人工校正。</p>
  {"".join(sections)}
  <p class="foot">產生時間：{html.escape(catalog["generated"])} · 共 {catalog["total_videos"]} 支影片 · 已處理 {catalog["processed_lessons"]} 講</p>
</body>
</html>
"""


def main() -> int:
    synced = sync_all_transcripts()
    print(f"Synced {synced} transcripts to YouTubeProcess.")

    videos = manifest_by_id()
    lessons: list[dict] = []
    processed = 0

    for vid in sorted(videos.keys(), key=lambda i: (videos[i]["course"], videos[i]["title"])):
        item = lesson_status(vid)
        ld = lesson_dir(vid)
        if item["has_video"] or item["has_board_ocr"] or ld.exists():
            write_lesson_meta(vid)
            processed += 1
            page_dir = ld
            page_dir.mkdir(parents=True, exist_ok=True)
            page_path = page_dir / "index.html"
            page_path.write_text(render_lesson_page(item, page_dir), encoding="utf-8")
            item["lesson_page"] = relpath_from(YOUTUBE_PROCESS_ROOT, page_path)
        catalog_item = {k: v for k, v in item.items() if k not in ("segments", "ocr_frames")}
        lessons.append(catalog_item)

    catalog = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(videos),
        "processed_lessons": processed,
        "lessons": lessons,
    }
    (YOUTUBE_PROCESS_ROOT / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (YOUTUBE_PROCESS_ROOT / "index.html").write_text(render_index(catalog), encoding="utf-8")
    print(f"Wrote {YOUTUBE_PROCESS_ROOT / 'index.html'}")
    print(f"Lessons with pages: {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
