#!/usr/bin/env python3
"""Build research style index from Yu-Hsiang Cheng publications.

Sources:
  - https://homepage.ntu.edu.tw/~yuhsiang/publications.html
  - https://www.ee.ntu.edu.tw/publist1.php?id=1080803 (fallback)
  - Google Scholar labels (manual seed): user=8ap6DXEAAAAJ

Outputs:
  - references/sources/publications/publications_raw.json
  - references/sources/publications/research_index.json
  - references/research/13-research-style-publications.md

Usage:
  python build_research_profile.py
  python build_research_profile.py --from-file path/to/publications.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
PUB_DIR = ROOT / "references" / "sources" / "publications"
OUT_JSON = PUB_DIR / "research_index.json"
RAW_JSON = PUB_DIR / "publications_raw.json"
OUT_MD = ROOT / "references" / "research" / "13-research-style-publications.md"
ARCHIVE_HTML = PUB_DIR / "publications.html"

HOMEPAGE_URL = "https://homepage.ntu.edu.tw/~yuhsiang/publications.html"
NTU_EE_URL = "https://www.ee.ntu.edu.tw/publist1.php?id=1080803"
SCHOLAR_URL = "https://scholar.google.com/citations?user=8ap6DXEAAAAJ&hl=en"

YEAR_RE = re.compile(r"\((\d{4})\)\s*\.?\s*$")
TITLE_LINK_RE = re.compile(
    r"[“\"]([^”\"]+)[”\"]\s*,?\s*(?:<a[^>]+>)?([^<(]+?)(?:\(([^)]+)\))?\s*\((\d{4})\)",
    re.I,
)
MARKDOWN_TITLE_RE = re.compile(
    r"[“\"]([^”\"]+)[”\"]\s*,?\s*([^,]+?)\s*\((\d{4})\)",
    re.I,
)
PLAIN_ENTRY_RE = re.compile(
    r"Yu-Hsiang Cheng[,\s]+[“\"]([^”\"]+)[”\"]",
    re.I,
)
SECTION_MARKERS = ("Journals", "Conferences", "Patents", "Others")


# Topic taxonomy: patterns → research theme for advising
TOPIC_TAXONOMY: list[dict] = [
    {
        "id": "thz_communications",
        "label_zh": "THz 通信與 6G",
        "label_en": "THz communications / 6G",
        "patterns": [
            r"\b6G\b",
            r"communication",
            r"wireless",
            r"data link",
            r"QAM",
            r"Gbps",
            r"RIS\b",
            r"reconfigurable metasurface",
        ],
        "advice": [
            "先釐清頻段（140 / 290 / 300 GHz）與鏈路預算，再拆成源、收發、天線、封裝。",
            "低成本可製造性（PCB、IPD、波導轉接）常比極致單點性能更重要。",
            "設計完要規劃量測：遠場、探針、CATR 或 WR 轉接是否可行。",
        ],
    },
    {
        "id": "thz_antenna_pcb",
        "label_zh": "THz 天線與 PCB/波導",
        "label_en": "THz antennas & waveguides",
        "patterns": [
            r"antenna",
            r"Vivaldi",
            r"SIW",
            r"substrate integrated",
            r"horn",
            r"slot array",
            r"reflectarray",
            r"transmitarray",
            r"Yagi",
            r"WR-3",
            r"waveguide",
            r"metasurface",
            r"metamaterial",
        ],
        "advice": [
            "feature size 能否用 PCB/CNC/雷射加工做出來，是選題第一關。",
            "天線幾乎一定要連同轉接結構（WR、微帶、SIW）一起設計與量測。",
            "陣列問題先確認饋電與校準流程，再談增益與波束。",
        ],
    },
    {
        "id": "thz_cmos_rfic",
        "label_zh": "THz CMOS / RFIC",
        "label_en": "THz CMOS IC",
        "patterns": [
            r"CMOS",
            r"LNA",
            r"mixer",
            r"VCO",
            r"RFIC",
            r"transformer",
            r"Gmax",
            r"push-push",
            r"D-band",
            r"bidirectional",
        ],
        "advice": [
            "先選製程節點與可用 fmax，再決定架構（LNA、混頻、VCO）。",
            "匹配網路與封裝寄生常是瓶頸；模擬要留 on-chip + package 餘裕。",
            "論文/專題要同時報 NF、增益、頻寬與功耗，避免只秀單點。",
        ],
    },
    {
        "id": "thz_passive_filter",
        "label_zh": "THz 被動元件（濾波/耦合）",
        "label_en": "THz passive components",
        "patterns": [
            r"filter",
            r"coupler",
            r"diplexer",
            r"resonator",
            r"branch line",
            r"EBG",
            r"FSS",
        ],
        "advice": [
            "金屬波導平台損耗低但加工成本要納入；可評估 CNC + 雷射微加工路線。",
            "可用 AI/ANN/Bayesian 做初版，但仍需 EM 全波驗證與加工公差分析。",
        ],
    },
    {
        "id": "thz_tds_sensing",
        "label_zh": "THz-TDS 光譜與感測",
        "label_en": "THz-TDS spectroscopy & sensing",
        "patterns": [
            r"TDS",
            r"time-domain spectroscopy",
            r"permittivity",
            r"dielectric",
            r"salt particle",
            r"imaging",
            r"sensor",
            r"polarizer",
            r"laser (?:direct )?writ",
            r"micromachin",
        ],
        "advice": [
            "先建立參考樣品與校準流程，再量未知材料參數。",
            "解析度與動態範圍取決於掃描時間與 SNR；說清楚取捨。",
            "薄膜/微粒感測要交代樣品製備與重複性。",
        ],
    },
    {
        "id": "ultrafast_single_shot",
        "label_zh": "超快單次泵浦探測",
        "label_en": "Ultrafast single-shot spectroscopy",
        "patterns": [
            r"single-shot",
            r"pump-probe",
            r"ultrafast",
            r"femtosecond",
            r"photoinduced",
            r"phase transition",
            r"metastable",
            r"coherent (?:lattice|phonon|control)",
            r"amorphization",
            r"manganite",
            r"OPA",
            r"noncollinear",
        ],
        "advice": [
            "先問現象時間尺度：ms/us 用電探針，ps/fs 才需要超快光路。",
            "不可逆過程優先考慮 single-shot，而非慢掃描平均。",
            "光路穩定、時間零點、探測器動態範圍要在實驗日誌裡可追溯。",
        ],
    },
    {
        "id": "nonlinear_microscopy",
        "label_zh": "非線性顯微與生醫光子",
        "label_en": "Nonlinear / biomedical photonics",
        "patterns": [
            r"harmonic generation",
            r"photoacoustic",
            r"two-photon",
            r"microscopy",
            r"oral cancer",
            r"biopsy",
            r"HbA1c",
            r"third harmonic",
        ],
        "advice": [
            "生醫影像題目要同時有光學對比機制與臨床/樣本倉庫合作路徑。",
            "解析度、穿透深度、成像速度三者通常只能先優化兩項。",
        ],
    },
    {
        "id": "em_ai_design",
        "label_zh": "AI 輔助電磁設計",
        "label_en": "AI-assisted EM design",
        "patterns": [
            r"artificial neural network",
            r"\bANN\b",
            r"Bayesian optimization",
            r"machine learning",
            r"pixelated design",
        ],
        "advice": [
            "AI 產出是初稿，不是簽核；全波模擬與加工公差仍必做。",
            "訓練資料要涵蓋你關心的頻寬與幾何範圍，否則外插會翻車。",
        ],
    },
]

SCHOLAR_SEED = {
    "profile_url": SCHOLAR_URL,
    "verified_labels": ["THz electronics", "Ultrafast spectroscopy"],
    "affiliation": "National Taiwan University",
    "note": "Scholar 頁面需人工瀏覽；自動抓取常被擋。標籤已手動寫入。",
}

RESEARCH_HEURISTICS = [
    {
        "id": "spectrum_first",
        "title": "頻譜定位優先",
        "text": "先問工作在微波、mmWave、THz 還是光學哪一段；邊界處往往有新應用。",
    },
    {
        "id": "design_measure_loop",
        "title": "設計—量測閉環",
        "text": "論文與專題應規劃『做出來、量得到、跟模擬對得起來』三階段。",
    },
    {
        "id": "cost_aware_fab",
        "title": "可製造性與成本",
        "text": "偏好 PCB、CNC、雷射直寫等可重複流程，而非一次性的貴重加工。",
    },
    {
        "id": "dual_path",
        "title": "電子／光子雙路徑",
        "text": "通信偏電子組（電路+天線）；光譜成像偏光子組（飛秒+TDS）；必要時用 UTC-PD 橋接。",
    },
    {
        "id": "student_ownership",
        "title": "學生主導、老師把關",
        "text": "學生常為一作發表會議；題目要能在 1–2 年內收斂成可量測的里程碑。",
    },
    {
        "id": "collaboration",
        "title": "跨組合作",
        "text": "CMOS、封裝、光電源、材料動力學等題目常與外校/外系共著。",
    },
]


def fetch_url(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; cheng-yu-hsiang-skill/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_publications_text(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm"}:
        return html_to_text(raw), str(path)
    return raw, str(path)


def html_to_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"</h[1-6]>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_line(line: str) -> str:
    line = unescape(line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def parse_publications_text(text: str) -> list[dict]:
    entries: list[dict] = []
    section = "unknown"
    for raw_line in text.splitlines():
        line = normalize_line(raw_line)
        if not line:
            continue
        if line in SECTION_MARKERS or line.startswith("## "):
            section = line.replace("## ", "").strip().lower()
            continue
        if len(line) < 20:
            continue
        if "Yu-Hsiang Cheng" not in line:
            continue
        if section == "unknown" and not line.startswith("#"):
            pass

        year_m = YEAR_RE.search(line) or re.search(r",\s*(\d{4})\s*\.?\s*(?:\(|$)", line) or re.search(r"\((\d{4})\)", line)
        year = int(year_m.group(1)) if year_m else None

        title = ""
        venue = ""
        m = TITLE_LINK_RE.search(line) or MARKDOWN_TITLE_RE.search(line)
        if m:
            title = m.group(1).strip()
            if m.lastindex and m.lastindex >= 3:
                venue = (m.group(2) if m.lastindex >= 2 else "").strip()
        if not title:
            m2 = re.search(r"[“\"]([^”\"]{8,})[”\"]", line)
            if m2:
                title = m2.group(1).strip()

        role = "unknown"
        if re.search(r"Yu-Hsiang Cheng[,\s]+[“\"]", line):
            role = "first_or_sole"
        elif line.startswith("Yu-Hsiang Cheng,") or line.startswith("Yu-Hsiang Cheng "):
            role = "first_or_sole"
        elif "Yu-Hsiang Cheng" in line:
            role = "coauthor"

        invited = bool(re.search(r"\(Invited\)|Invited", line, re.I))
        award = bool(re.search(r"Best Paper|Travel Grant|Award", line, re.I))

        if not title and len(line) > 30:
            title = line[:120]

        entries.append(
            {
                "section": section.lower(),
                "title": title,
                "venue": venue,
                "year": year,
                "role": role,
                "invited": invited,
                "award": award,
                "raw_line": line[:500],
            }
        )
    return entries


def detect_topics(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for topic in TOPIC_TAXONOMY:
        if any(re.search(p, lower, re.I) or re.search(p, text) for p in topic["patterns"]):
            found.append(topic["id"])
    return found


def build_keyword_stats(entries: list[dict]) -> dict:
    topic_counts: Counter = Counter()
    keyword_counts: Counter = Counter()
    by_year: dict[str, list[str]] = defaultdict(list)

    for e in entries:
        blob = f"{e.get('title', '')} {e.get('venue', '')} {e.get('raw_line', '')}"
        topics = detect_topics(blob)
        for t in topics:
            topic_counts[t] += 1
        if e.get("year"):
            by_year[str(e["year"])].extend(topics)

        # flat keywords from patterns
        for topic in TOPIC_TAXONOMY:
            for pat in topic["patterns"]:
                if re.search(pat, blob, re.I):
                    keyword_counts[pat.strip("\\b")] += 1

    return {
        "topic_counts": dict(topic_counts.most_common()),
        "top_keywords": keyword_counts.most_common(40),
        "topics_by_year": {y: dict(Counter(ts)) for y, ts in sorted(by_year.items())},
    }


def career_phases(entries: list[dict]) -> list[dict]:
    phases = [
        {
            "id": "ntu_photonics_phd",
            "label": "台大光電博士（孫效宇組）",
            "years": "2011–2013",
            "signals": ["harmonic", "photoacoustic", "microscopy", "oral cancer"],
        },
        {
            "id": "mit_ultrafast",
            "label": "MIT 超快光譜（Nelson 組）",
            "years": "2013–2019",
            "signals": ["single-shot", "pump-probe", "phase transition", "femtosecond", "PRL", "PRX"],
        },
        {
            "id": "ntu_thz_pi",
            "label": "台大 THz 光電 PI",
            "years": "2019–",
            "signals": ["300 GHz", "CMOS", "SIW", "antenna", "6G", "TDS"],
        },
    ]
    for phase in phases:
        phase["entry_count"] = sum(
            1
            for e in entries
            if e.get("year")
            and (
                (phase["id"] == "ntu_photonics_phd" and e["year"] <= 2015)
                or (phase["id"] == "mit_ultrafast" and 2015 < e["year"] <= 2019)
                or (phase["id"] == "ntu_thz_pi" and e["year"] >= 2019)
            )
            and any(s.lower() in (e.get("title", "") + e.get("raw_line", "")).lower() for s in phase["signals"])
        )
    return phases


def build_markdown(index: dict) -> str:
    stats = index["stats"]
    lines = [
        "# Agent 13：研究風格與著作關鍵字",
        "",
        f"調研時間：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "資料來源：",
        f"- [實驗室 Publications]({HOMEPAGE_URL})",
        f"- [Google Scholar]({SCHOLAR_URL})（標籤：THz electronics、Ultrafast spectroscopy）",
        f"- [台大電機著作列表]({NTU_EE_URL})",
        "",
        "## 覆蓋狀態",
        "",
        f"- 解析條目：**{stats['total_entries']}**（期刊 {stats['journals']} · 會議 {stats['conferences']} · 其他 {stats['others']}）",
        f"- 年份範圍：**{stats['year_min']}–{stats['year_max']}**",
        f"- 一作/主講傾向條目：**{stats['first_or_sole']}**",
        "",
        "## 研究關鍵字主題（依著作統計）",
        "",
        "| 主題 ID | 中文 | 出現次數 |",
        "|---------|------|----------|",
    ]
    for tid, count in sorted(index["keyword_stats"]["topic_counts"].items(), key=lambda x: -x[1]):
        label = next((t["label_zh"] for t in TOPIC_TAXONOMY if t["id"] == tid), tid)
        lines.append(f"| `{tid}` | {label} | {count} |")

    lines += ["", "## 研究規劃啟發式（鄭宇翔視角）", ""]
    for h in index["research_heuristics"]:
        lines.append(f"### {h['title']}")
        lines.append(f"- {h['text']}")
        lines.append("")

    lines += ["## 各主題給研究建議時的檢查清單", ""]
    for topic in TOPIC_TAXONOMY:
        count = index["keyword_stats"]["topic_counts"].get(topic["id"], 0)
        if count == 0:
            continue
        lines.append(f"### {topic['label_zh']} (`{topic['id']}`，{count} 篇次)")
        for tip in topic["advice"]:
            lines.append(f"- {tip}")
        lines.append("")

    lines += [
        "## 職涯階段與代表作方向",
        "",
    ]
    for phase in index["career_phases"]:
        lines.append(f"- **{phase['label']}**（{phase['years']}）：相關條目約 {phase['entry_count']} 筆")

    lines += [
        "",
        "## 高頻技術詞（pattern 命中）",
        "",
    ]
    for kw, count in index["keyword_stats"]["top_keywords"][:25]:
        lines.append(f"- `{kw}` × {count}")

    lines += [
        "",
        "## Skill 調用指引",
        "",
        "使用者問**研究選題、讀書規劃、實驗設計、論文方向**時：",
        "1. 讀 `references/sources/publications/research_index.json` 的 `topic_taxonomy` 與 `keyword_stats`",
        "2. 對照 `references/research/10-lab-research-directions.md` 看實驗室雙路徑",
        "3. 用本檔啟發式 + 主題 checklist 給**可執行里程碑**（設計→製作→量測）",
        "4. 超快/材料動力學題目加查 `ultrafast_single_shot`；通信題目加查 `thz_communications` + `thz_cmos_rfic`",
        "",
        "更新：`python scripts/build_research_profile.py`",
        "",
    ]

    lines += ["## 近期期刊代表作（節錄）", ""]
    for e in index["highlight_journals"][:12]:
        lines.append(f"- ({e['year']}) {e['title']}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build research profile from publications")
    parser.add_argument("--from-file", type=Path, help="Use local HTML/text instead of fetching")
    args = parser.parse_args()

    PUB_DIR.mkdir(parents=True, exist_ok=True)

    if args.from_file and args.from_file.is_file():
        text, source = load_publications_text(args.from_file)
    elif ARCHIVE_HTML.is_file():
        text, source = load_publications_text(ARCHIVE_HTML)
        try:
            fetched = fetch_url(HOMEPAGE_URL)
            ARCHIVE_HTML.write_text(fetched, encoding="utf-8")
            text, source = load_publications_text(ARCHIVE_HTML)
            source = HOMEPAGE_URL
        except Exception as exc:  # noqa: BLE001
            print(f"Fetch failed ({exc}); using cached archive", file=sys.stderr)
    else:
        archive_txt = PUB_DIR / "publications_archive.txt"
        if archive_txt.is_file():
            text, source = load_publications_text(archive_txt)
        else:
            try:
                fetched = fetch_url(HOMEPAGE_URL)
                ARCHIVE_HTML.write_text(fetched, encoding="utf-8")
                text, source = load_publications_text(ARCHIVE_HTML)
                source = HOMEPAGE_URL
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to fetch publications: {exc}", file=sys.stderr)
                return 1

    entries = parse_publications_text(text)

    # dedupe by title+year
    seen: set[tuple] = set()
    unique: list[dict] = []
    for e in entries:
        key = (e.get("title", "")[:80], e.get("year"))
        if key in seen:
            continue
        seen.add(key)
        for t in detect_topics(f"{e.get('title','')} {e.get('raw_line','')}"):
            e.setdefault("topics", []).append(t)
        unique.append(e)

    years = [e["year"] for e in unique if e.get("year")]
    stats = {
        "total_entries": len(unique),
        "journals": sum(1 for e in unique if e.get("section") == "journals"),
        "conferences": sum(1 for e in unique if e.get("section") == "conferences"),
        "others": sum(1 for e in unique if e.get("section") not in ("journals", "conferences")),
        "first_or_sole": sum(1 for e in unique if e.get("role") == "first_or_sole"),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
    }

    keyword_stats = build_keyword_stats(unique)
    highlight_journals = sorted(
        [e for e in unique if e.get("section") == "journals" and e.get("year")],
        key=lambda x: (-(x.get("year") or 0), x.get("title", "")),
    )

    index = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source,
        "scholar": SCHOLAR_SEED,
        "stats": stats,
        "keyword_stats": keyword_stats,
        "topic_taxonomy": [
            {
                "id": t["id"],
                "label_zh": t["label_zh"],
                "label_en": t["label_en"],
                "advice": t["advice"],
                "patterns": t["patterns"],
            }
            for t in TOPIC_TAXONOMY
        ],
        "research_heuristics": RESEARCH_HEURISTICS,
        "career_phases": career_phases(unique),
        "highlight_journals": highlight_journals[:20],
        "entries": unique,
    }

    RAW_JSON.write_text(json.dumps({"source": source, "entries": unique}, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(build_markdown(index), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(f"  entries: {stats['total_entries']} (journals {stats['journals']}, conferences {stats['conferences']})")
    print(f"  topics: {len(keyword_stats['topic_counts'])} themes detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
