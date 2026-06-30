#!/usr/bin/env python3
"""Aggregate YouTube info.json metadata into curriculum summary."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META_DIR = ROOT / "references" / "sources" / "youtube" / "meta"
OUT_MD = ROOT / "references" / "research" / "09-youtube-corpus.md"

COURSE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("em", re.compile(r"電磁學|electromagnetism|Electromagnetics", re.I)),
    ("fourier_optics", re.compile(r"傅立葉|Fourier transform and Fourier optics|Fresnel|Fraunhofer|Holography|diffraction|Angular spectrum", re.I)),
    ("rf_microwave", re.compile(r"射頻|RF and microwave|微波系統|Bandpass|Butterworth|PLL|Receiver|HFSS|Chebyshev|Bessel", re.I)),
    ("radio_life", re.compile(r"生活中的電波|Radio waves in our life", re.I)),
    ("podcast", re.compile(r"未來雜貨電|EP8[567]", re.I)),
    ("demo", re.compile(r"PLUTO|SDR|demo|hologram|Rubik", re.I)),
]


def classify(title: str) -> str:
    for name, pat in COURSE_RULES:
        if pat.search(title):
            return name
    return "other"


def load_videos() -> list[dict]:
    videos = []
    for path in sorted(META_DIR.glob("*.info.json")):
        if path.name.startswith("UC"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        title = data.get("title") or ""
        videos.append(
            {
                "id": data.get("id"),
                "title": title,
                "course": classify(title),
                "duration": data.get("duration"),
                "upload_date": data.get("upload_date"),
                "description": (data.get("description") or "").strip(),
                "chapters": data.get("chapters") or [],
                "url": data.get("webpage_url") or f"https://www.youtube.com/watch?v={data.get('id')}",
            }
        )
    return videos


def lecture_number(title: str) -> tuple[int, str] | None:
    m = re.search(r"電磁學一\s*(\d+)", title)
    if m:
        return int(m.group(1)), "em1"
    m = re.search(r"微波系統導論\s*(\d+)", title)
    if m:
        return int(m.group(1)), "rf"
    m = re.search(r"傅立葉轉換與光學\s*(\d+)", title)
    if m:
        return int(m.group(1)), "fo"
    return None


def build_markdown(videos: list[dict]) -> str:
    by_course: dict[str, list[dict]] = defaultdict(list)
    for v in videos:
        by_course[v["course"]].append(v)

    for items in by_course.values():
        items.sort(key=lambda x: (lecture_number(x["title"]) or (999, ""), x["title"]))

    counts = Counter(v["course"] for v in videos)
    total_hours = sum((v["duration"] or 0) for v in videos) / 3600

    lines = [
        "# Agent 9：YouTube 教學語料 — 鄭宇翔",
        "",
        f"調研時間：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        "## 頻道概況",
        "",
        "- 頻道：[鄭宇翔 Yu-Hsiang Cheng](https://www.youtube.com/channel/UCkVcI3rBHx2t49mdCsHLG4w)",
        "- 影片總數：**224**",
        f"- 總時長約：**{total_hours:.1f} 小時**",
        "- 字幕狀態：**218/224 無 YouTube 字幕**；僅 6 支有自動字幕（多為英文／非課程主體）",
        "- 本機 ASR（Whisper）因 torch DLL 問題暫未能批次轉錄；已保留 `scripts/crawl_youtube_transcripts.py` 供後續環境修復後使用",
        "",
        "## 課程分類統計",
        "",
        "| 類別 | 支數 | 教學用途 |",
        "|------|------|----------|",
    ]

    course_labels = {
        "em": "電磁學一（核心 EM 理論）",
        "fourier_optics": "傅立葉轉換與光學",
        "rf_microwave": "射頻與微波系統",
        "radio_life": "生活中的電波",
        "podcast": "訪談／科普",
        "demo": "實驗 demo／業餘興趣",
        "other": "其他（含業餘無線電、科普短片）",
    }
    for key in ["em", "fourier_optics", "rf_microwave", "radio_life", "podcast", "demo", "other"]:
        lines.append(f"| {course_labels[key]} | {counts.get(key, 0)} | skill 教學參照 |")

    lines += [
        "",
        "## 電磁學一單元地圖（依影片標題整理）",
        "",
        "鄭宇翔電磁學課程自 2019 Fall 起每年錄影上傳；標題呈現**向量 → 靜電 → 靜磁 → 波動 → 傳輸線/波導/天線 → 介質/散射**的經典脈絡。",
        "",
    ]

    em_titles = [v for v in by_course["em"] if "電磁學" in v["title"]]
    for v in em_titles:
        num = lecture_number(v["title"])
        prefix = f"{num[0]:02d}. " if num else "- "
        mins = (v["duration"] or 0) // 60
        lines.append(f"{prefix}[{v['title']}]({v['url']})（約 {mins} 分）")

    lines += [
        "",
        "## 傅立葉光學單元地圖",
        "",
        "從波動光學／電磁基礎 → 繞射公式 → 角譜 → 透鏡傅立葉轉換性質 → 成像系統 → 全息與類比光學資訊處理。",
        "",
    ]
    for v in by_course["fourier_optics"]:
        mins = (v["duration"] or 0) // 60
        lines.append(f"- [{v['title']}]({v['url']})（約 {mins} 分）")

    lines += [
        "",
        "## 射頻與微波單元地圖",
        "",
        "濾波器設計（Butterworth/Chebyshev/Bessel）→ 傳輸線諧振帶通 → 功率增益 → 接收機 → PLL → HFSS 實作。",
        "",
    ]
    for v in by_course["rf_microwave"]:
        mins = (v["duration"] or 0) // 60
        lines.append(f"- [{v['title']}]({v['url']})（約 {mins} 分）")

    lines += [
        "",
        "## 從 metadata 蒸餾的教學 DNA（待逐字稿補強）",
        "",
        "### 電磁學教學法",
        "1. **由淺入深、幾何先行**：向量代數 → 梯度散度旋度 → 座標系，再進場論。",
        "2. **先物理圖像再公式**：靜電/靜磁分開建立直覺，再用 Maxwell 統一。",
        "3. **工程接軌**：傳輸線、波導、天線、介質與散射——不停在課本習題。",
        "4. **開放可及**：完整錄影上傳，與 OCW／IACP 課程大綱對齊。",
        "",
        "### 光學教學法",
        "1. **從 Huygens-Fresnel 到角譜**：把繞射看成平面波分解。",
        "2. **透鏡 = 光學傅立葉處理器**：4f 系統、相干/非相干成像分開講。",
        "3. **連到資訊處理**：類比光學運算、全息、超解析——呼應 THz 成像研究。",
        "",
        "### 對外科普語氣（與 LINE PI 語氣不同）",
        "- 用微波爐、GPS、WiFi 等日常物件降低陌生感（呼應「生活中的電波」）。",
        "- 安全議題用**數據與標準**說話，不用恐慌性語言。",
        "- 有耐心、會舉例，但推導仍要求學生回到數學。",
        "",
        "## 有字幕的影片（已抓逐字稿）",
        "",
    ]

    transcript_dir = ROOT / "references" / "sources" / "youtube" / "transcripts"
    if transcript_dir.exists():
        for p in sorted(transcript_dir.glob("*.txt")):
            text = p.read_text(encoding="utf-8")
            vid = p.stem.split("_")[0]
            match = next((v for v in videos if v["id"] == vid), None)
            title = match["title"] if match else vid
            lines.append(f"- [{title}](https://www.youtube.com/watch?v={vid}) — {len(text)} 字")

    lines += [
        "",
        "## 資訊缺口與後續",
        "",
        "1. **主體課程無字幕**：需 ASR（建議修復 torch/ffmpeg 後跑 `crawl_youtube_transcripts.py --course em --max 10`）。",
        "2. **優先轉錄清單**：電磁學一 1/10/20/30/40、傅立葉光學 18/19/24、射頻 18/23。",
        "3. **交叉驗證**：NTU OCW、Coursera「生活中的電波」課程文字可補科普段落。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    videos = load_videos()
    OUT_MD.write_text(build_markdown(videos), encoding="utf-8")
    print(f"Wrote {OUT_MD} ({len(videos)} videos)")


if __name__ == "__main__":
    main()
