#!/usr/bin/env python3
"""從 pttweb.cc 爬取指定使用者的 PTT 發文、留言、暱稱紀錄。

用法:
  python scripts/crawl_ptt_pttweb.py chengfred
  python scripts/crawl_ptt_pttweb.py chengfred --max-pages 3   # 測試用

輸出目錄: references/sources/ptt/
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

BASE = "https://www.pttweb.cc/user"
HEADERS = {"User-Agent": "Mozilla/5.0 (skill-generator research bot)"}
DELAY_SEC = 1.0


def get_max_page(soup: BeautifulSoup) -> int | None:
    nums = [int(a.get_text(strip=True)) for a in soup.select("a") if a.get_text(strip=True).isdigit()]
    return max(nums) if nums else None


def fetch_page(username: str, kind: str, page: int) -> BeautifulSoup | None:
    params = {"t": kind, "page": page}
    url = f"{BASE}/{username}?{urlencode(params)}"
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def parse_thread_items(soup: BeautifulSoup) -> list[dict]:
    items = []
    for el in soup.select("div.thread-item"):
        text = el.get_text("\n", strip=True)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            continue
        title = lines[0]
        board = ""
        meta = ""
        for ln in lines[1:]:
            if ln.startswith("[") and ln.endswith("]"):
                board = ln.strip("[]")
            elif "作者:" in ln or "發表於" in ln:
                meta = ln
        items.append({"title": title, "board": board, "meta": meta, "raw": text})
    return items


def parse_messages(soup: BeautifulSoup) -> list[dict]:
    """留言頁：擷取推文/回文片段。"""
    items = []
    for el in soup.select("div.thread-item"):
        text = el.get_text("\n", strip=True)
        # 擷取 chengfred 的推文行
        pushes = []
        for ln in text.split("\n"):
            ln = ln.strip()
            if re.search(r"[推→噓]chengfred:", ln) or re.search(r"→chengfred:", ln):
                pushes.append(ln)
        items.append({
            "context": text[:300],
            "pushes": pushes,
            "raw": text,
        })
    return items


def crawl_kind(username: str, kind: str, max_pages: int | None) -> list[dict]:
    all_items: list[dict] = []
    seen_titles: set[str] = set()
    page = 1
    site_max: int | None = None
    while True:
        if max_pages is not None and page > max_pages:
            break
        if site_max is not None and page > site_max:
            break
        soup = fetch_page(username, kind, page)
        if soup is None:
            break
        if site_max is None:
            site_max = get_max_page(soup)
        else:
            m = get_max_page(soup)
            if m:
                site_max = max(site_max, m)
        if kind == "message":
            batch = parse_messages(soup)
        else:
            batch = parse_thread_items(soup)
        if not batch:
            break
        new_batch = []
        for row in batch:
            key = row.get("raw", "")[:120]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            row["page"] = page
            new_batch.append(row)
        if not new_batch:
            break
        all_items.extend(new_batch)
        print(f"  [{kind}] page {page}/{site_max or '?'}: +{len(new_batch)} (total {len(all_items)})")
        page += 1
        time.sleep(DELAY_SEC)
    return all_items


def crawl_nicknames(username: str) -> list[dict]:
    soup = fetch_page(username, "nickname", 1)
    if soup is None:
        return []
    nicknames = []
    text = soup.get_text("\n", strip=True)
    for m in re.finditer(r"暱稱：(.+?)\n文章數量：(\d+)", text):
        nicknames.append({"nickname": m.group(1), "count": int(m.group(2))})
    return nicknames


def main() -> None:
    parser = argparse.ArgumentParser(description="爬取 pttweb.cc 使用者紀錄")
    parser.add_argument("username", help="PTT ID，例如 chengfred")
    parser.add_argument("--max-pages", type=int, default=None, help="每類型最多頁數（測試用）")
    parser.add_argument("--out", type=Path, default=None, help="輸出目錄")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    out_dir = args.out or (skill_root / "references" / "sources" / "ptt")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"爬取 https://www.pttweb.cc/user/{args.username} ...")
    articles = crawl_kind(args.username, "article", args.max_pages)
    messages = crawl_kind(args.username, "message", args.max_pages)
    nicknames = crawl_nicknames(args.username)

    # 從留言頁額外抽出純推文文字
    push_lines = []
    for m in messages:
        push_lines.extend(m.get("pushes", []))

    payload = {
        "username": args.username,
        "source": f"https://www.pttweb.cc/user/{args.username}",
        "stats": {
            "articles": len(articles),
            "message_pages_items": len(messages),
            "push_lines": len(push_lines),
            "nicknames": nicknames,
        },
        "nicknames": nicknames,
        "articles": articles,
        "messages": messages,
        "push_lines": push_lines,
    }

    out_json = out_dir / f"{args.username}_pttweb.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 純文字摘要供 skill 閱讀
    md_lines = [
        f"# PTT 語料：{args.username}",
        f"",
        f"來源：[pttweb.cc 作者頁]({payload['source']})",
        f"",
        f"## 統計",
        f"- 發文：{len(articles)} 篇",
        f"- 留言頁項目：{len(messages)} 則",
        f"- 擷取推文行：{len(push_lines)} 行",
        f"- 暱稱：{', '.join(n['nickname'] for n in nicknames)}",
        f"",
        f"## 推文樣本（前 50 行）",
        f"",
    ]
    for ln in push_lines[:50]:
        md_lines.append(f"- {ln}")
    (out_dir / f"{args.username}_summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(f"完成 → {out_json}")
    print(f"摘要 → {out_dir / f'{args.username}_summary.md'}")


if __name__ == "__main__":
    main()
