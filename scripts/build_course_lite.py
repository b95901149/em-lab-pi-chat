#!/usr/bin/env python3
"""Build static 'chengfred YouTube Course Lite' site (YouTube embed, deployable)."""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from transcript_utils import find_skill_transcript, load_segments, parse_transcript_header, segment_sync_is_realtime
from youtube_process_paths import (
    COURSE_LABELS,
    COURSE_ORDER,
    WORKSPACE_ROOT,
    lesson_sort_key,
    manifest_by_id,
)

LITE_ROOT = WORKSPACE_ROOT / "chengfred YouTube Course Lite"
CHANNEL_URL = "https://www.youtube.com/channel/UCkVcI3rBHx2t49mdCsHLG4w"
CHANNEL_NAME = "鄭宇翔 Yu-Hsiang Cheng"

STYLE_CSS = """\
:root {
  --bg: #f6f8fb;
  --card: #fff;
  --text: #1a1a1a;
  --muted: #5f6368;
  --accent: #0b57d0;
  --accent-soft: #e8f0fe;
  --warn-bg: #fff8e1;
  --warn-border: #f9a825;
  --border: #e0e4ea;
  --radius: 10px;
  --shadow: 0 1px 3px rgba(0,0,0,.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { max-width: 1100px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
.hero {
  background: linear-gradient(135deg, #0b57d0 0%, #1a73e8 45%, #34a853 100%);
  color: #fff;
  padding: 2.5rem 1.25rem 2rem;
}
.hero .wrap { padding-top: 0; padding-bottom: 0; }
.hero h1 { margin: 0 0 .4rem; font-size: 1.85rem; font-weight: 700; }
.hero p { margin: .35rem 0; opacity: .95; }
.hero .links a { color: #fff; font-weight: 600; }
.stats {
  display: flex; flex-wrap: wrap; gap: .75rem; margin: 1.25rem 0 0;
}
.stat {
  background: rgba(255,255,255,.15);
  border-radius: 8px;
  padding: .55rem .9rem;
  font-size: .92rem;
}
.notice {
  margin: 1.25rem 0;
  padding: .85rem 1rem;
  background: var(--warn-bg);
  border-left: 4px solid var(--warn-border);
  border-radius: 6px;
  color: #5f4339;
  font-size: .95rem;
}
.toolbar {
  display: flex; flex-wrap: wrap; gap: .75rem; align-items: center;
  margin: 1.5rem 0 1rem;
}
#search {
  flex: 1 1 220px;
  padding: .65rem .85rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 1rem;
}
.filters { display: flex; flex-wrap: wrap; gap: .4rem; }
.filter-btn {
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 999px;
  padding: .35rem .85rem;
  cursor: pointer;
  font-size: .88rem;
}
.filter-btn.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}
.course-block {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  margin: 1.25rem 0;
  overflow: hidden;
}
.course-block h2 {
  margin: 0;
  padding: .85rem 1rem;
  font-size: 1.15rem;
  background: #f8fafc;
  border-bottom: 1px solid var(--border);
}
.lesson-table { width: 100%; border-collapse: collapse; }
.lesson-table th, .lesson-table td {
  text-align: left;
  padding: .55rem 1rem;
  border-bottom: 1px solid #eef1f5;
  vertical-align: top;
}
.lesson-table th { font-size: .82rem; color: var(--muted); font-weight: 600; }
.lesson-table tr:hover td { background: #f8fbff; }
.badge {
  display: inline-block;
  font-size: .75rem;
  padding: .12rem .45rem;
  border-radius: 4px;
  background: #e8f5e9;
  color: #2e7d32;
}
.badge.muted { background: #f1f3f4; color: #5f6368; }
.badge.warn { background: #fff3e0; color: #e65100; border: 1px solid #ffcc80; }
.notice-sync {
  margin: .75rem 0 0;
  padding: .7rem .9rem;
  background: #fff3e0;
  border-left: 4px solid #fb8c00;
  border-radius: 6px;
  color: #5d4037;
  font-size: .92rem;
}
.empty { color: var(--muted); padding: 1rem; }
.foot { color: var(--muted); font-size: .88rem; margin-top: 2rem; }

/* lesson page */
.lesson-hero { padding: 1.25rem 0 .5rem; }
.lesson-hero h1 { margin: 0 0 .35rem; font-size: 1.45rem; }
.meta { color: var(--muted); font-size: .92rem; }
.player-stack {
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
  background: #000;
  margin: 1rem 0;
}
.player-stack .yt-wrap {
  position: relative;
  width: 100%;
  padding-bottom: 56.25%;
  height: 0;
}
.player-stack #yt-player-mount {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
}
.player-stack .yt-iframe {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  border: 0;
}
.yt-fallback {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
  background: #1e1e1e;
  color: #e8eaed;
  text-align: center;
  font-size: .95rem;
}
.yt-fallback p { margin: .4rem 0; }
.yt-fallback a { color: #8ab4f8; }
.subtitle-bar {
  display: flex; align-items: flex-start; gap: .75rem;
  min-height: 3rem; padding: .7rem 1rem;
  background: #1e1e1e; color: #f5f5f5;
}
.subtitle-bar .subtitle-time {
  flex-shrink: 0; color: #9aa0a6; font-size: .85em;
  font-variant-numeric: tabular-nums;
}
.subtitle-bar .subtitle-text { flex: 1; line-height: 1.45; }
.transcript-wrap { margin: 1.5rem 0 2rem; }
.transcript-wrap h2 { font-size: 1.1rem; margin-bottom: .5rem; }
.transcript-wrap .hint { font-size: .85em; font-weight: normal; color: var(--muted); }
.transcript-viewport {
  height: 16rem; overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
}
.seg {
  padding: .45rem .85rem;
  cursor: pointer;
  border-left: 3px solid transparent;
}
.seg:hover { background: #f5f8ff; }
.seg.active { background: #fff8e1; border-left-color: var(--warn-border); }
.seg .time {
  color: var(--muted); font-size: .85em;
  margin-right: .55rem;
  font-variant-numeric: tabular-nums;
}
.nav-top { margin-bottom: 1rem; font-size: .95rem; }
@media (max-width: 640px) {
  .lesson-table th:nth-child(3), .lesson-table td:nth-child(3) { display: none; }
}
"""

SITE_JS = """\
(function() {
  const dataEl = document.getElementById("catalog-data");
  if (!dataEl) return;
  const catalog = JSON.parse(dataEl.textContent);
  const lessons = catalog.lessons || [];
  const searchEl = document.getElementById("search");
  const filterBar = document.getElementById("course-filters");
  const container = document.getElementById("course-sections");
  let activeCourse = "all";
  let query = "";

  const courses = catalog.course_order || [];
  const labels = catalog.course_labels || {};

  function norm(s) { return (s || "").toLowerCase(); }

  function filtered() {
    const q = norm(query);
    return lessons.filter((l) => {
      if (activeCourse !== "all" && l.course !== activeCourse) return false;
      if (!q) return true;
      const hay = [l.title, l.video_id, l.course_label, l.preview].join(" ").toLowerCase();
      return hay.includes(q);
    });
  }

  function renderFilters() {
    if (!filterBar) return;
    const btns = [{ id: "all", label: "全部" }];
    for (const c of courses) {
      const n = lessons.filter((x) => x.course === c).length;
      if (n) btns.push({ id: c, label: (labels[c] || c) + " (" + n + ")" });
    }
    filterBar.innerHTML = btns.map((b) =>
      '<button type="button" class="filter-btn' + (activeCourse === b.id ? " active" : "") +
      '" data-course="' + b.id + '">' + b.label + '</button>'
    ).join("");
    filterBar.querySelectorAll(".filter-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeCourse = btn.dataset.course;
        renderFilters();
        renderSections();
      });
    });
  }

  function renderSections() {
    if (!container) return;
    const items = filtered();
    const byCourse = {};
    for (const l of items) {
      (byCourse[l.course] = byCourse[l.course] || []).push(l);
    }
    const order = activeCourse === "all" ? courses : [activeCourse];
    let html = "";
    for (const c of order) {
      const rows = byCourse[c];
      if (!rows || !rows.length) continue;
      html += '<section class="course-block" id="course-' + c + '">';
      html += "<h2>" + (labels[c] || c) + "</h2>";
      html += '<table class="lesson-table"><thead><tr><th>講次</th><th>長度</th><th>資料</th></tr></thead><tbody>';
      for (const l of rows) {
        const flags = [];
        if (l.has_transcript) flags.push('<span class="badge">逐字稿</span>');
        else flags.push('<span class="badge muted">無逐字稿</span>');
        if (l.has_segments && l.realtime_sync) flags.push('<span class="badge">時間軸</span>');
        else if (l.has_segments) flags.push('<span class="badge warn">字幕尚未即時同步</span>');
        html += "<tr><td><a href=\\"" + l.page + "\\">" + escapeHtml(l.title) + "</a></td>";
        html += "<td>" + (l.duration || "—") + "</td>";
        html += "<td>" + flags.join(" ") + "</td></tr>";
      }
      html += "</tbody></table></section>";
    }
    if (!html) html = '<p class="empty">沒有符合的講次。</p>';
    container.innerHTML = html;
    const countEl = document.getElementById("result-count");
    if (countEl) countEl.textContent = "顯示 " + items.length + " / " + lessons.length + " 講";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  if (searchEl) {
    searchEl.addEventListener("input", () => {
      query = searchEl.value.trim();
      renderSections();
    });
  }
  renderFilters();
  renderSections();
})();
"""

REFERRER_META = '<meta name="referrer" content="strict-origin-when-cross-origin"/>'

LESSON_PLAYER_JS = """\
(function() {
  const cfg = window.LESSON_CONFIG;
  if (!cfg) return;

  let ytPlayer = null;
  let segments = [];
  let activeIdx = -1;
  let autoScroll = true;
  let scrollPauseTimer = null;
  let tickTimer = null;

  function fmt(sec) {
    const s = Math.floor(sec % 60).toString().padStart(2, "0");
    const m = Math.floor(sec / 60);
    return m + ":" + s;
  }

  function embedOrigin() {
    const o = window.location.origin;
    if (!o || o === "null" || o.startsWith("file:")) return null;
    return o;
  }

  function buildEmbedUrl(videoId, origin) {
    const params = new URLSearchParams({
      enablejsapi: "1",
      rel: "0",
      modestbranding: "1",
      playsinline: "1",
      origin: origin,
    });
    return "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(videoId) + "?" + params.toString();
  }

  function youtubeWatchUrl(sec) {
    return "https://www.youtube.com/watch?v=" + encodeURIComponent(cfg.videoId) + "&t=" + Math.floor(sec) + "s";
  }

  function getTime() {
    if (ytPlayer && typeof ytPlayer.getCurrentTime === "function") {
      try { return ytPlayer.getCurrentTime() || 0; } catch (e) { return 0; }
    }
    return 0;
  }

  window.seekLesson = function(sec) {
    const t = Math.max(0, Number(sec) || 0);
    if (ytPlayer && typeof ytPlayer.seekTo === "function") {
      try {
        ytPlayer.seekTo(t, true);
        ytPlayer.playVideo();
        return;
      } catch (e) {}
    }
    window.open(youtubeWatchUrl(t), "_blank", "noopener");
  };

  function showFileProtocolNotice(mount) {
    mount.innerHTML =
      '<div class="yt-fallback">' +
      '<p>直接開啟本機 HTML 檔案（<code>file://</code>）無法嵌入 YouTube 播放器。</p>' +
      '<p>請執行 <code>serve.bat</code>，以 <a href="http://localhost:8767/index.html">http://localhost:8767</a> 瀏覽；' +
      '或 <a href="' + youtubeWatchUrl(0) + '" target="_blank" rel="noopener">在 YouTube 觀看</a>。</p>' +
      "</div>";
  }

  function mountIframe(mount, origin) {
    const iframe = document.createElement("iframe");
    iframe.id = "yt-player";
    iframe.className = "yt-iframe";
    iframe.src = buildEmbedUrl(cfg.videoId, origin);
    iframe.title = "YouTube video player";
    iframe.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    iframe.setAttribute(
      "allow",
      "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
    );
    iframe.setAttribute("allowfullscreen", "");
    mount.innerHTML = "";
    mount.appendChild(iframe);
    return iframe;
  }

  function initTranscript() {
    const dataEl = document.getElementById("segments-data");
    const track = document.getElementById("transcript-track");
    const viewport = document.getElementById("transcript-viewport");
    if (!dataEl || !track) return;
    segments = JSON.parse(dataEl.textContent);
    if (!segments.length) return;

    const subtitleBar = document.getElementById("subtitle-bar");
    function updateSubtitle(idx) {
      if (!subtitleBar || idx < 0) return;
      const seg = segments[idx];
      subtitleBar.querySelector(".subtitle-time").textContent = fmt(seg.start);
      subtitleBar.querySelector(".subtitle-text").textContent = seg.text;
    }

    function pauseAutoScroll() {
      autoScroll = false;
      clearTimeout(scrollPauseTimer);
      scrollPauseTimer = setTimeout(() => { autoScroll = true; }, 5000);
    }
    if (viewport) {
      viewport.addEventListener("wheel", pauseAutoScroll, { passive: true });
      viewport.addEventListener("mousedown", pauseAutoScroll);
      viewport.addEventListener("touchstart", pauseAutoScroll, { passive: true });
    }

    segments.forEach((seg, i) => {
      const div = document.createElement("div");
      div.className = "seg";
      const time = document.createElement("span");
      time.className = "time";
      time.textContent = fmt(seg.start);
      const text = document.createElement("span");
      text.className = "text";
      text.textContent = seg.text;
      div.appendChild(time);
      div.appendChild(text);
      div.addEventListener("click", () => {
        autoScroll = true;
        clearTimeout(scrollPauseTimer);
        seekLesson(seg.start);
      });
      track.appendChild(div);
    });

    function findActive(t) {
      for (let i = 0; i < segments.length; i++) {
        const s = segments[i];
        if (t >= s.start && t < s.end) return i;
      }
      if (t < segments[0].start) return 0;
      return segments.length - 1;
    }

    function scrollToSegment(idx) {
      const el = track.children[idx];
      if (!el || !viewport || !autoScroll) return;
      const target = el.offsetTop - viewport.clientHeight / 2 + el.offsetHeight / 2;
      const maxScroll = viewport.scrollHeight - viewport.clientHeight;
      viewport.scrollTo({ top: Math.max(0, Math.min(target, maxScroll)), behavior: "smooth" });
    }

    function setActive(idx) {
      if (idx < 0) return;
      const changed = idx !== activeIdx;
      activeIdx = idx;
      for (let i = 0; i < track.children.length; i++) {
        track.children[i].classList.toggle("active", i === idx);
      }
      if (changed) {
        updateSubtitle(idx);
        scrollToSegment(idx);
      }
    }

    function syncFromPlayer() {
      setActive(findActive(getTime()));
    }

    syncFromPlayer();
    tickTimer = setInterval(syncFromPlayer, 300);
    window.addEventListener("beforeunload", () => clearInterval(tickTimer));
    window.addEventListener("resize", () => scrollToSegment(activeIdx));
  }

  function bindPlayer(iframe) {
    function onReady() {
      const el = ytPlayer && ytPlayer.getIframe ? ytPlayer.getIframe() : iframe;
      if (el) el.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
      initTranscript();
    }

    window.onYouTubeIframeAPIReady = function() {
      ytPlayer = new YT.Player(iframe, {
        host: "https://www.youtube-nocookie.com",
        events: { onReady: onReady },
      });
    };

    if (window.YT && window.YT.Player) {
      window.onYouTubeIframeAPIReady();
    } else {
      const tag = document.createElement("script");
      tag.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(tag);
    }
  }

  const mount = document.getElementById("yt-player-mount");
  if (!mount) return;

  const origin = embedOrigin();
  if (!origin) {
    showFileProtocolNotice(mount);
    initTranscript();
    return;
  }

  const iframe = mountIframe(mount, origin);
  bindPlayer(iframe);
})();
"""


def fmt_duration(sec: float | None) -> str:
    if not sec:
        return "—"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def transcript_preview(video_id: str, limit: int = 120) -> str:
    txt = find_skill_transcript(video_id)
    if not txt:
        return ""
    _, body = parse_transcript_header(txt.read_text(encoding="utf-8"))
    body = re.sub(r"\s+", " ", body).strip()
    return body[:limit] + ("…" if len(body) > limit else "")


def lesson_page_name(video_id: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", video_id).strip() or "unknown"
    return f"{safe}.html"


def build_lesson_entry(v: dict) -> dict:
    vid = v["id"]
    course = v.get("course") or "other"
    segments = load_segments(vid, v.get("duration"))
    has_transcript = find_skill_transcript(vid) is not None
    return {
        "video_id": vid,
        "title": v.get("title") or vid,
        "course": course,
        "course_label": COURSE_LABELS.get(course, course),
        "url": v.get("url") or f"https://www.youtube.com/watch?v={vid}",
        "duration_sec": v.get("duration"),
        "duration": fmt_duration(v.get("duration")),
        "has_transcript": has_transcript,
        "has_segments": bool(segments),
        "realtime_sync": segment_sync_is_realtime(vid) if segments else False,
        "preview": transcript_preview(vid),
        "page": f"lessons/{lesson_page_name(vid)}",
    }


def render_lesson_page(entry: dict, segments: list[dict]) -> str:
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

    player_scripts = f"""
  <script>window.LESSON_CONFIG = {{ videoId: {json.dumps(vid)} }};</script>
  <script src="../assets/lesson-player.js"></script>"""

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
            "點擊跳轉可能略有偏差；板書擷取流程完成後會改為 Whisper 精準對齊。</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  {REFERRER_META}
  <title>{html.escape(entry["title"])} — {CHANNEL_NAME}</title>
  <link rel="stylesheet" href="../assets/style.css"/>
</head>
<body>
  <div class="wrap">
    <p class="nav-top"><a href="../index.html">← 課程總覽</a></p>
    <div class="lesson-hero">
      <h1>{html.escape(entry["title"])}</h1>
      <p class="meta">{html.escape(entry["course_label"])} · {entry["duration"]} · ID <code>{html.escape(vid)}</code></p>
      <p class="meta"><a href="{html.escape(entry["url"])}" target="_blank" rel="noopener">在 YouTube 開啟</a></p>
    </div>
    <section class="player-stack">
      <div class="yt-wrap"><div id="yt-player-mount"></div></div>
      {subtitle_bar}
    </section>
    <p class="notice">逐字稿由語音辨識自動生成，尚未人工校正。</p>
    {sync_notice}
    {transcript_section}
  </div>{player_scripts}
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
  <title>{CHANNEL_NAME} — 課程索引 Lite</title>
  <link rel="stylesheet" href="assets/style.css"/>
</head>
<body>
  <header class="hero">
    <div class="wrap">
      <h1>{CHANNEL_NAME} 課程索引</h1>
      <p>YouTube 嵌入播放 · 同步逐字稿 · 可部署至網頁主機或本機開啟</p>
      <p class="links"><a href="{CHANNEL_URL}" target="_blank" rel="noopener">YouTube 頻道</a></p>
      <div class="stats">
        <span class="stat">共 {stats["total"]} 支影片</span>
        <span class="stat">{stats["with_transcript"]} 支含逐字稿</span>
        <span class="stat">{stats["with_segments"]} 支含時間軸</span>
        <span class="stat">{stats["courses"]} 大課程系列</span>
      </div>
    </div>
  </header>
  <main class="wrap">
    <p class="notice">備註：逐字稿由語音辨識自動生成，尚未人工校正。影片直接嵌入 YouTube，無需下載本機 MP4。本機預覽請執行 <code>serve.bat</code>（勿直接雙擊 HTML）。</p>
    <div class="toolbar">
      <input id="search" type="search" placeholder="搜尋講次標題、關鍵字…" autocomplete="off"/>
      <span id="result-count" class="meta"></span>
    </div>
    <div id="course-filters" class="filters"></div>
    <div id="course-sections"></div>
    <p class="foot">產生時間：{html.escape(catalog["generated"])} · Lite 靜態版</p>
  </main>
  <script id="catalog-data" type="application/json">{cat_json}</script>
  <script src="assets/site.js"></script>
</body>
</html>
"""


def main() -> int:
    videos = list(manifest_by_id().values())
    videos.sort(key=lambda v: (v.get("course", ""), lesson_sort_key(v.get("title") or "", v.get("course") or "")))

    assets_dir = LITE_ROOT / "assets"
    lessons_dir = LITE_ROOT / "lessons"
    assets_dir.mkdir(parents=True, exist_ok=True)
    lessons_dir.mkdir(parents=True, exist_ok=True)

    (assets_dir / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (assets_dir / "site.js").write_text(SITE_JS, encoding="utf-8")
    (assets_dir / "lesson-player.js").write_text(LESSON_PLAYER_JS, encoding="utf-8")

    lessons: list[dict] = []
    with_segments = 0
    with_transcript = 0

    for v in videos:
        entry = build_lesson_entry(v)
        lessons.append(entry)
        if entry["has_transcript"]:
            with_transcript += 1
        segments = load_segments(v["id"], v.get("duration"))
        if segments:
            with_segments += 1
        page_path = lessons_dir / lesson_page_name(v["id"])
        page_path.write_text(render_lesson_page(entry, segments), encoding="utf-8")

    # Sort lessons within catalog for stable order
    lessons.sort(key=lambda x: (x["course"], lesson_sort_key(x["title"], x["course"])))

    catalog = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "channel_url": CHANNEL_URL,
        "channel_name": CHANNEL_NAME,
        "course_order": COURSE_ORDER,
        "course_labels": COURSE_LABELS,
        "stats": {
            "total": len(lessons),
            "with_transcript": with_transcript,
            "with_segments": with_segments,
            "courses": len({l["course"] for l in lessons if l["course"] in COURSE_ORDER}),
        },
        "lessons": lessons,
    }

    (LITE_ROOT / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (LITE_ROOT / "index.html").write_text(render_index(catalog), encoding="utf-8")

    serve_bat = LITE_ROOT / "serve.bat"
    serve_script = SCRIPTS / "serve_course_lite.py"
    serve_bat.write_text(
        "@echo off\n"
        f'cd /d "{LITE_ROOT}"\n'
        f'C:\\ProgramData\\anaconda3\\python.exe "{serve_script}"\n',
        encoding="utf-8",
    )

    (LITE_ROOT / ".htaccess").write_text(
        "<IfModule mod_headers.c>\n"
        '  Header always set Referrer-Policy "strict-origin-when-cross-origin"\n'
        "</IfModule>\n",
        encoding="utf-8",
    )

    (LITE_ROOT / "_headers").write_text(
        "/*\n  Referrer-Policy: strict-origin-when-cross-origin\n",
        encoding="utf-8",
    )

    print(f"Wrote {LITE_ROOT}")
    print(f"  lessons: {len(lessons)}")
    print(f"  with transcript: {with_transcript}")
    print(f"  with segments: {with_segments}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
