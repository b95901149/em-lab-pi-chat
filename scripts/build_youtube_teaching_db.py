#!/usr/bin/env python3
"""Build YouTube teaching database from transcripts for skill invocation.

Reads references/sources/youtube/transcripts/*.txt
Outputs:
  - references/sources/youtube/teaching_index.json
  - references/research/11-youtube-teaching-style.md

Usage:
  python build_youtube_teaching_db.py
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YOUTUBE_DIR = ROOT / "references" / "sources" / "youtube"
TRANSCRIPTS_DIR = YOUTUBE_DIR / "transcripts"
MANIFEST_PATH = YOUTUBE_DIR / "manifest.json"
INDEX_PATH = YOUTUBE_DIR / "teaching_index.json"
OUT_MD = ROOT / "references" / "research" / "11-youtube-teaching-style.md"

HEADER_RE = re.compile(r"^# (.+)$", re.M)
VIDEO_ID_RE = re.compile(r"^# video_id: (.+)$", re.M)
COURSE_RE = re.compile(r"^# course: (.+)$", re.M)
SOURCE_RE = re.compile(r"^# source: (.+)$", re.M)

# 授課風格特徵片語（出現頻率用於蒸餾）
STYLE_MARKERS = [
    "好不好",
    "大家",
    "高中",
    "線性代數",
    "生活中的電波",
    "右手定則",
    "不要背",
    "概念",
    "推給",
    "其他老師",
    "我個人認為",
    "滿簡單",
    "不用背",
    "站在巨人",
    "傅立葉",
    "模擬",
    "量測",
    "頻譜",
    "微波爐",
    "WiFi",
    "不懂要問",
    "寫字",
    "動手",
    "期中考",
    "作業",
    "YouTube",
    "開放",
]

TOPIC_KEYWORDS = {
    "vector_algebra": ["向量", "vector", "內積", "外積", "unit vector", "unevector"],
    "coordinates": ["座標", "coordinate", "柱", "球", "gradient", "梯度", "散度", "旋度"],
    "electrostatics": ["電場", "electric field", "庫倫", "高斯", "gauss", "靜電"],
    "magnetostatics": ["磁場", "magnetic", "ampere", "faraday", "lorentz"],
    "maxwell_waves": ["maxwell", "波動", "wave", "平面波", "poynting", "麥克斯韋"],
    "materials": ["介質", "導體", "半導體", "dielectric", "boundary", "邊界"],
    "transmission_line": ["傳輸線", "transmission line", "smith", "匹配", "matching"],
    "antenna": ["天線", "antenna", "輻射", "radiation"],
    "optics_diffraction": ["繞射", "diffraction", "fresnel", "fraunhofer", "角譜"],
    "fourier_optics": ["傅立葉", "透鏡", "lens", "4f", "成像", "holography", "全息"],
    "filters_rf": ["濾波器", "filter", "butterworth", "bandpass", "pll"],
    "daily_apps": ["微波爐", "gps", "wifi", "手機", "生活中的電波", "安全"],
}


def parse_transcript(path: Path, manifest_by_id: dict[str, dict]) -> dict:
    raw = path.read_text(encoding="utf-8")
    header_end = raw.find("\n\n")
    header = raw[:header_end] if header_end > 0 else ""
    body = raw[header_end + 2 :].strip() if header_end > 0 else raw.strip()

    def grab(pattern: re.Pattern[str]) -> str:
        m = pattern.search(header)
        return m.group(1).strip() if m else ""

    vid = grab(VIDEO_ID_RE) or path.stem.split("_")[0]
    title = grab(HEADER_RE) or path.stem
    course = grab(COURSE_RE) or "unknown"
    if course == "unknown" and vid in manifest_by_id:
        course = manifest_by_id[vid].get("course", "unknown")
        if title == path.stem:
            title = manifest_by_id[vid].get("title", title)
    source = grab(SOURCE_RE) or "unknown"

    return {
        "video_id": vid,
        "title": title,
        "course": course,
        "source": source,
        "transcript_path": str(path.relative_to(ROOT)),
        "word_count": len(body),
        "char_count": len(body.replace(" ", "")),
        "body_preview": body[:400],
        "body": body,
    }


def detect_topics(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for topic, kws in TOPIC_KEYWORDS.items():
        if any(kw.lower() in lower or kw in text for kw in kws):
            found.append(topic)
    return found


def count_markers(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in STYLE_MARKERS:
        c = text.count(m)
        if c:
            counts[m] = c
    return counts


def lecture_num(title: str) -> int | None:
    for pat in (r"電磁學一\s*(\d+)", r"微波系統導論\s*(\d+)", r"傅[立氏].*?(\d+)"):
        m = re.search(pat, title)
        if m:
            return int(m.group(1))
    return None


def build_teaching_style_summary(all_markers: Counter, entries: list[dict]) -> dict:
    total_words = sum(e["word_count"] for e in entries)
    courses = Counter(e["course"] for e in entries)
    return {
        "total_transcripts": len(entries),
        "total_words": total_words,
        "by_course": dict(courses),
        "top_phrases": all_markers.most_common(25),
        "voice_traits": [
            "口語化、常問「好不好」確認學生跟上",
            "強調高中已學基礎，不重複死背公式",
            "鼓勵動手寫推導（「電磁學是一門應該寫字的課」）",
            "會自嘲、會聊開學/遠距/小班等課堂瑣事，拉近距離",
            "偶爾岔到「生活中的電波」通識內容當调剂",
            "把部分內容「推給其他老師」或高中（線性代數、行列式）",
            "用日常比喻解抽象符號（unit vector、hat、內積外積幾何意義）",
            "對進度有掌控：期中考前鋪墊、前半學期較慢較細",
        ],
        "pedagogy_patterns": [
            "先符號與幾何圖像，再代數運算",
            "當場帶做習題（1.4 等）示範速度與格式",
            "明講哪些不用背（查表即可）、哪些必須熟練（內積外積、行列式）",
            "右手定則等空間概念要求用手比",
            "向量分析整章耐心鋪墊，為後續場論打底",
        ],
        "explain_em_concept_protocol": [
            "1. 一句話說物理圖像（場在哪、邊界怎麼變）",
            "2. 寫出核心公式與符號定義",
            "3. 用簡單特例或對稱性檢查",
            "4. 連到作業/期中考或工程應用",
            "5. 鼓勵學生問，但先自己試過",
        ],
    }


def build_markdown(index: dict) -> str:
    s = index["teaching_style"]
    lines = [
        "# Agent 11：YouTube 授課風格與內容資料庫",
        "",
        f"調研時間：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"資料來源：[鄭宇翔 YouTube 頻道](https://www.youtube.com/channel/UCkVcI3rBHx2t49mdCsHLG4w) 逐字稿（ASR）",
        "",
        "## 覆蓋狀態",
        "",
        f"- 已建逐字稿：**{s['total_transcripts']}** 支",
        f"- 總字數約：**{s['total_words']:,}** 字",
        f"- 機讀索引：`references/sources/youtube/teaching_index.json`",
        "",
        "### 各課程覆蓋",
        "",
        "| 課程 | 支數 |",
        "|------|------|",
    ]
    for course, n in sorted(s["by_course"].items()):
        lines.append(f"| {course} | {n} |")

    lines += [
        "",
        "## 授課語氣（副人格 · YouTube）",
        "",
        "與 LINE 實驗室 PI 語氣不同：對學生**較有耐心**、節奏較慢、允許暫時聽不懂。",
        "",
    ]
    for t in s["voice_traits"]:
        lines.append(f"- {t}")

    lines += ["", "## 教學法模式", ""]
    for p in s["pedagogy_patterns"]:
        lines.append(f"- {p}")

    lines += ["", "## 講解電磁/光學概念時的流程", ""]
    for step in s["explain_em_concept_protocol"]:
        lines.append(f"- {step}")

    lines += ["", "## 高頻用語（逐字稿統計）", ""]
    for phrase, count in s["top_phrases"][:20]:
        lines.append(f"- 「{phrase}」× {count}")

    lines += ["", "## 逐講索引", ""]
    for e in index["lectures"]:
        topics = ", ".join(e.get("topics", [])[:5]) or "—"
        lines.append(
            f"- [{e['title']}]({e['url']}) — {e['word_count']} 字 | 主題: {topics}"
        )
        if e.get("preview"):
            lines.append(f"  - 開場摘要：{e['preview'][:120]}…")

    lines += [
        "",
        "## Skill 調用指引",
        "",
        "回答電磁學/光學/微波教學問題時：",
        "1. 查 `teaching_index.json` 找同主題講次",
        "2. 讀對應 `transcripts/*.txt` 確認用語與例子",
        "3. 切換 **YouTube 教學副人格**（見 SKILL.md）",
        "4. 可引用講次編號與 YouTube 連結",
        "",
        "批次轉錄進行中時，重新執行 `python scripts/build_youtube_teaching_db.py` 更新本檔。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    entries: list[dict] = []
    all_markers: Counter = Counter()

    manifest_by_id: dict[str, dict] = {}
    if MANIFEST_PATH.exists():
        m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest_by_id = {v["id"]: v for v in m.get("videos", []) if v.get("id")}

    for path in sorted(TRANSCRIPTS_DIR.glob("*.txt")):
        item = parse_transcript(path, manifest_by_id)
        item["topics"] = detect_topics(item["body"])
        item["style_markers"] = count_markers(item["body"])
        all_markers.update(item["style_markers"])
        item["lecture_number"] = lecture_num(item["title"])
        item["url"] = f"https://www.youtube.com/watch?v={item['video_id']}"
        item["preview"] = item.pop("body_preview")
        del item["body"]
        entries.append(item)

    entries.sort(key=lambda e: (e["course"], e.get("lecture_number") or 999, e["title"]))

    manifest_stats = {}
    if MANIFEST_PATH.exists():
        m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest_stats = m.get("transcript_stats", {})

    style = build_teaching_style_summary(all_markers, entries)
    index = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "channel_url": "https://www.youtube.com/channel/UCkVcI3rBHx2t49mdCsHLG4w",
        "manifest_stats": manifest_stats,
        "teaching_style": style,
        "lectures": entries,
    }

    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(build_markdown(index), encoding="utf-8")
    print(f"Wrote {INDEX_PATH} ({len(entries)} transcripts)")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
