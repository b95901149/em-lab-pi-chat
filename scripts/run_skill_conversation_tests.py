#!/usr/bin/env python3
"""Automated smoke tests for cheng-yu-hsiang-perspective Skill assets and triggers."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_ROOT / "SKILL.md"
GUIDE_MD = SKILL_ROOT / "使用說明.md"
RESEARCH_INDEX = SKILL_ROOT / "references/sources/publications/research_index.json"
TEACHING_INDEX = SKILL_ROOT / "references/sources/youtube/teaching_index.json"
MANIFEST = SKILL_ROOT / "references/sources/youtube/manifest.json"
LINE_CORPUS = SKILL_ROOT / "references/sources/line/chengfred_line_messages.txt"
SANSHA = SKILL_ROOT / "references/research/12-sansha-mode.md"

TRIGGER_KEYWORDS = [
    "鄭宇翔視角",
    "chengfred",
    "三思模式",
    "太赫茲",
    "yuhsiang perspective",
]

TEST_PROMPTS = [
    {
        "id": "T1",
        "name": "觸發＋頻譜教學",
        "user": "用鄭宇翔視角解釋：什麼是太赫茲？它在頻譜上站哪裡？",
        "expect": ["頻譜", "微波", "光學", "繁體中文"],
        "persona": "teaching",
    },
    {
        "id": "T2",
        "name": "教學語氣（4f 系統）",
        "user": "4f 系統為什麼能做空間頻率濾波？",
        "expect": ["傅立葉", "透鏡", "空間頻率"],
        "persona": "teaching",
    },
    {
        "id": "T3",
        "name": "研究選題：THz 天線方向",
        "user": "老師，我想做有關 Terahertz 天線的研究，可以給我一些方向嗎？",
        "expect": ["頻譜", "feature size", "轉接", "里程碑", "CATR"],
        "persona": "research",
    },
    {
        "id": "T3b",
        "name": "研究選題：300 GHz 里程碑",
        "user": "我想做 300 GHz 天線，chengfred 會建議從哪裡開始？給 3 個月里程碑。",
        "expect": ["模擬", "量測", "里程碑"],
        "persona": "research",
    },
    {
        "id": "T4",
        "name": "三思模式",
        "user": "開啟三思模式。幫我規劃 300 GHz 天線 CST 模擬。",
        "expect": ["三思 Checklist", "一思", "二思", "三思", "mesh"],
        "persona": "sansha",
    },
    {
        "id": "T5",
        "name": "誠實邊界",
        "user": "鄭教授會怎麼看：這檔股票該買嗎？",
        "expect": ["超出", "專業"],
        "persona": "boundary",
    },
    {
        "id": "T6",
        "name": "LINE PI 語氣",
        "user": "論文初稿下週可以交嗎？（鄭宇翔模式）",
        "expect": ["提前", "deadline", "確認"],
        "persona": "line_pi",
    },
    {
        "id": "T7",
        "name": "口試準備",
        "user": "我打算下個月進行口試，可以幫我想一下有哪些東西要注意嗎？",
        "expect": ["口試", "投影片", "口委", "mock", "NAS"],
        "persona": "line_pi",
    },
    {
        "id": "T8",
        "name": "三思模式：天線量測",
        "user": "開啟三思模式。明天跟老師約要量天線，我今天要準備哪些東西？",
        "expect": ["三思 Checklist", "一思", "量測", "校準", "NAS"],
        "persona": "sansha",
    },
    {
        "id": "T9",
        "name": "演講出席與拍照紀錄",
        "user": "老師，您要我明天參加某個演講並拍照紀錄，請問有哪些東西是我要注意的？",
        "expect": ["拍照", "slide", "檔名", "回報", "提前"],
        "persona": "line_pi",
    },
    {
        "id": "T10",
        "name": "口試委員約時間 email",
        "user": "要怎麼寫信跟口試委員約時間？",
        "expect": ["email", "副本", "口委", "時段", "正式"],
        "persona": "line_pi",
    },
    {
        "id": "T11",
        "name": "Lab 聚餐",
        "user": "下學期的聚餐你想吃什麼？",
        "expect": ["聚餐", "人數", "合菜", "便當", "投票"],
        "persona": "line_pi",
    },
]


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_file(path: Path, label: str) -> CheckResult:
    if path.exists() and path.stat().st_size > 0:
        return CheckResult(label, True, f"OK ({path.stat().st_size:,} bytes)")
    return CheckResult(label, False, f"Missing or empty: {path}")


def check_skill_frontmatter() -> CheckResult:
    text = SKILL_MD.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return CheckResult("SKILL frontmatter", False, "No YAML frontmatter")
    m = re.search(r"^name:\s*cheng-yu-hsiang-perspective", text, re.M)
    if not m:
        return CheckResult("SKILL frontmatter", False, "name field mismatch")
    for kw in ("三思模式", "繁體中文", "chengfred"):
        if kw not in text:
            return CheckResult("SKILL frontmatter", False, f"Missing keyword: {kw}")
    return CheckResult("SKILL frontmatter", True, "name + key triggers present")


def check_triggers_in_skill() -> CheckResult:
    text = SKILL_MD.read_text(encoding="utf-8")
    missing = [k for k in TRIGGER_KEYWORDS if k not in text]
    if missing:
        return CheckResult("Trigger keywords", False, f"Missing: {missing}")
    return CheckResult("Trigger keywords", True, f"{len(TRIGGER_KEYWORDS)} keywords documented")


def check_research_index() -> CheckResult:
    data = json.loads(RESEARCH_INDEX.read_text(encoding="utf-8"))
    topics = data.get("topic_taxonomy") or []
    with_advice = sum(1 for t in topics if t.get("advice"))
    if with_advice < 5:
        return CheckResult("research_index.json", False, f"Only {with_advice} topics with advice")
    return CheckResult("research_index.json", True, f"{len(topics)} topics, {with_advice} with advice")


def check_teaching_index() -> CheckResult:
    data = json.loads(TEACHING_INDEX.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("entries") or data.get("videos") or []
    if len(entries) < 100:
        return CheckResult("teaching_index.json", False, f"Only {len(entries)} entries")
    courses = {e.get("course") for e in entries if isinstance(e, dict)}
    for need in ("em", "fourier_optics", "rf_microwave"):
        if need not in courses:
            return CheckResult("teaching_index.json", False, f"Missing course: {need}")
    return CheckResult("teaching_index.json", True, f"{len(entries)} entries, courses={sorted(c for c in courses if c)}")


def check_manifest_stats() -> CheckResult:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    stats = data.get("transcript_stats") or {}
    with_tx = stats.get("with_transcript") or stats.get("with_transcripts")
    total = stats.get("total_videos") or len(data.get("videos") or [])
    if not with_tx:
        return CheckResult("manifest.json", False, "No transcript_stats.with_transcript")
    return CheckResult("manifest.json", True, f"{with_tx}/{total} with transcript")


def check_sansha_doc() -> CheckResult:
    text = SANSHA.read_text(encoding="utf-8")
    for section in ("一思·釐清", "二思·驗證", "三思·交付"):
        if section not in text:
            return CheckResult("12-sansha-mode.md", False, f"Missing section: {section}")
    return CheckResult("12-sansha-mode.md", True, "Three-step framework present")


def check_line_corpus() -> CheckResult:
    lines = LINE_CORPUS.read_text(encoding="utf-8").splitlines()
    if len(lines) < 1000:
        return CheckResult("LINE corpus", False, f"Only {len(lines)} lines")
    return CheckResult("LINE corpus", True, f"{len(lines):,} lines")


def run_asset_checks() -> list[CheckResult]:
    return [
        check_file(SKILL_MD, "SKILL.md"),
        check_file(GUIDE_MD, "使用說明.md"),
        check_file(RESEARCH_INDEX, "research_index path"),
        check_file(TEACHING_INDEX, "teaching_index path"),
        check_file(MANIFEST, "manifest path"),
        check_file(LINE_CORPUS, "LINE corpus path"),
        check_file(SANSHA, "sansha doc path"),
        check_skill_frontmatter(),
        check_triggers_in_skill(),
        check_research_index(),
        check_teaching_index(),
        check_manifest_stats(),
        check_sansha_doc(),
        check_line_corpus(),
    ]


def print_prompt_catalog() -> None:
    print("\n=== 對話測試題庫（供 Agent 手動／自動驗證）===\n")
    for t in TEST_PROMPTS:
        print(f"[{t['id']}] {t['name']}")
        print(f"  用戶：{t['user']}")
        print(f"  預期含：{', '.join(t['expect'])}")
        print(f"  語氣：{t['persona']}\n")


def main() -> int:
    print("=== cheng-yu-hsiang-perspective Skill 自動測試 ===\n")
    print(f"Skill root: {SKILL_ROOT}\n")

    results = run_asset_checks()
    passed = sum(1 for r in results if r.ok)
    failed = [r for r in results if not r.ok]

    print("--- 資產與索引檢查 ---")
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"  [{mark}] {r.name}: {r.detail}")

    print(f"\nSummary: {passed}/{len(results)} passed")

    print_prompt_catalog()

    if failed:
        print("Some checks FAILED.")
        return 1
    print("All asset checks PASSED. Run conversation tests in Cursor with prompts above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
