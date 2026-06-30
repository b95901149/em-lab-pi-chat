#!/usr/bin/env python3
"""Build 使用說明.pdf from Markdown with optional internal/external hyperlinks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fpdf import FPDF

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from youtube_process_paths import WORKSPACE_ROOT

LITE_ROOT = WORKSPACE_ROOT / "chengfred YouTube Course Lite"
MD_PATH = LITE_ROOT / "使用說明.md"
PDF_PATH = LITE_ROOT / "使用說明.pdf"

FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msjh.ttc"),
    Path(r"C:\Windows\Fonts\msjhbd.ttc"),
    Path(r"C:\Windows\Fonts\mingliu.ttc"),
]

LINK_COLOR = (0, 102, 204)
TEXT_COLOR = (30, 30, 30)
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
TOC_ITEM_RE = re.compile(r"^(\d+)\.\s+\[([^\]]+)\]\(#([^)]+)\)\s*$")


def find_font() -> Path:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("找不到中文字型（msjh.ttc / mingliu.ttc）")


def normalize_text(text: str) -> str:
    return (
        text.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2610", "[ ]")
        .replace("\u2611", "[x]")
    )


def strip_md_inline(text: str) -> str:
    text = MD_LINK_RE.sub(r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return normalize_text(text)


def heading_anchor(title: str) -> str:
    """GitHub-style anchor slug aligned with 使用說明.md 目錄 links."""
    s = title.strip()
    paren_parts = re.findall(r"[（(]([^）)]+)[）)]", s)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    s = re.sub(r"\s*\.\s*", "-", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"[／/\\]", "-", s)
    s = re.sub(r"[：:]", "", s)
    s = re.sub(r"-+", "-", s)
    s = s.lower().strip("-")
    for part in paren_parts:
        extra = part.lower().strip()
        if re.search(r"[a-zA-Z]", part):
            extra = re.sub(r"\s+", "-", extra)
            extra = re.sub(r"[^0-9a-z-]", "", extra)
        else:
            extra = re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", extra)
        s += extra
    return s


def split_md_inline(text: str) -> list[tuple[str, ...]]:
    """Split into ('text', str) | ('internal', label, anchor) | ('external', label, url)."""
    parts: list[tuple[str, ...]] = []
    last = 0
    for m in MD_LINK_RE.finditer(text):
        if m.start() > last:
            chunk = normalize_text(text[last : m.start()])
            chunk = re.sub(r"\*\*([^*]+)\*\*", r"\1", chunk)
            chunk = re.sub(r"`([^`]+)`", r"\1", chunk)
            if chunk:
                parts.append(("text", chunk))
        label = normalize_text(m.group(1))
        href = m.group(2).strip()
        if href.startswith("#"):
            parts.append(("internal", label, href[1:]))
        else:
            parts.append(("external", label, href))
        last = m.end()
    if last < len(text):
        chunk = normalize_text(text[last:])
        chunk = re.sub(r"\*\*([^*]+)\*\*", r"\1", chunk)
        chunk = re.sub(r"`([^`]+)`", r"\1", chunk)
        if chunk:
            parts.append(("text", chunk))
    return parts


class GuidePDF(FPDF):
    def __init__(self, font_path: Path, *, enable_links: bool = False) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.font_path = font_path
        self.enable_links = enable_links
        self._font_ready = False
        self.section_links: dict[str, int] = {}
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 18, 18)

    def setup_font(self) -> None:
        if self._font_ready:
            return
        self.add_font("body", "", str(self.font_path))
        self.add_font("body", "B", str(self.font_path))
        self._font_ready = True

    def footer(self) -> None:
        self.setup_font()
        self.set_y(-12)
        self.set_font("body", "", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"第 {self.page_no()} 頁", align="C")

    def get_or_create_link(self, anchor: str) -> int:
        if anchor not in self.section_links:
            self.section_links[anchor] = self.add_link()
        return self.section_links[anchor]

    def set_anchor_here(self, anchor: str) -> None:
        if not self.enable_links or not anchor:
            return
        link = self.get_or_create_link(anchor)
        self.set_link(link, page=self.page_no(), y=self.get_y())

    def render_inline(
        self,
        text: str,
        *,
        h: float = 6.5,
        size: int = 11,
        bold: bool = False,
        prefix: str = "",
    ) -> None:
        self.setup_font()
        if self.get_y() > 270:
            self.add_page()
        self.set_x(self.l_margin)

        if prefix:
            self.set_font("body", "B" if bold else "", size)
            self.set_text_color(*TEXT_COLOR)
            self.write(h, prefix)

        if not self.enable_links or not MD_LINK_RE.search(text):
            self.set_font("body", "B" if bold else "", size)
            self.set_text_color(*TEXT_COLOR)
            self.write(h, strip_md_inline(text))
            self.ln(h + 1)
            return

        for part in split_md_inline(text):
            kind = part[0]
            if kind == "text":
                self.set_font("body", "B" if bold else "", size)
                self.set_text_color(*TEXT_COLOR)
                self.write(h, part[1])
            elif kind == "internal":
                self.set_font("body", "B" if bold else "", size)
                self.set_text_color(*LINK_COLOR)
                link = self.get_or_create_link(part[2])
                self.write(h, part[1], link=link)
            elif kind == "external":
                self.set_font("body", "B" if bold else "", size)
                self.set_text_color(*LINK_COLOR)
                self.write(h, part[1], link=part[2])
        self.ln(h + 1)

    def add_title(self, text: str, level: int, *, anchor: str | None = None) -> None:
        self.setup_font()
        sizes = {1: 18, 2: 14, 3: 12}
        size = sizes.get(level, 11)
        if self.get_y() > 20:
            self.ln(4)
        if anchor:
            self.set_anchor_here(anchor)
            if self.enable_links:
                try:
                    self.start_section(strip_md_inline(text), level=max(0, level - 1))
                except Exception:
                    pass
        self.set_font("body", "B", size)
        self.set_text_color(20, 20, 20)
        self.set_x(self.l_margin)
        self.multi_cell(0, size * 0.55, strip_md_inline(text))
        self.ln(2)

    def add_paragraph(self, text: str) -> None:
        if not text.strip():
            return
        self.render_inline(text)

    def add_bullet(self, text: str, indent: int = 0) -> None:
        if self.get_y() > 270:
            self.add_page()
        if indent:
            self.set_x(self.l_margin + indent)
        self.render_inline(text, prefix="• ")

    def add_numbered(self, num: str, text: str) -> None:
        self.render_inline(text, prefix=f"{num} ")

    def add_toc_item(self, num: str, label: str, anchor: str) -> None:
        if self.get_y() > 270:
            self.add_page()
        self.setup_font()
        self.set_x(self.l_margin)
        h = 6.5
        prefix = f"{num}. "
        if self.enable_links:
            self.set_font("body", "", 11)
            self.set_text_color(*TEXT_COLOR)
            self.write(h, prefix)
            self.set_text_color(*LINK_COLOR)
            link = self.get_or_create_link(anchor)
            self.write(h, label, link=link)
        else:
            self.set_font("body", "", 11)
            self.set_text_color(*TEXT_COLOR)
            self.write(h, f"{prefix}{label}")
        self.ln(h + 1)

    def add_code_block(self, lines: list[str]) -> None:
        if not lines:
            return
        self.setup_font()
        self.set_font("body", "", 9)
        self.set_fill_color(245, 247, 250)
        self.set_text_color(40, 40, 40)
        text = "\n".join(lines)
        self.set_x(self.l_margin)
        self.multi_cell(0, 5.2, text, fill=True)
        self.ln(2)

    def add_hr(self) -> None:
        y = self.get_y() + 2
        self.set_draw_color(220, 224, 230)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(6)

    def add_image_block(self, img_path: Path, caption: str = "") -> None:
        if not img_path.exists():
            self.add_paragraph(f"[圖片缺失: {img_path.name}]")
            return
        usable_w = self.w - self.l_margin - self.r_margin
        if self.get_y() > 200:
            self.add_page()
        try:
            self.image(str(img_path), w=usable_w)
        except Exception as exc:
            self.add_paragraph(f"[無法嵌入圖片 {img_path.name}: {exc}]")
            return
        if caption:
            self.setup_font()
            self.set_font("body", "", 9)
            self.set_text_color(100, 100, 100)
            self.multi_cell(0, 5, caption, align="C")
        self.ln(3)

    def add_table(self, rows: list[list[str]]) -> None:
        if not rows:
            return
        self.setup_font()
        col_count = max(len(r) for r in rows)
        usable_w = self.w - self.l_margin - self.r_margin
        col_w = usable_w / col_count
        line_h = 7
        for ridx, row in enumerate(rows):
            if self.get_y() > 270:
                self.add_page()
            self.set_x(self.l_margin)
            is_header = ridx == 0
            self.set_font("body", "B" if is_header else "", 10 if is_header else 9.5)
            self.set_fill_color(232, 240, 254) if is_header else self.set_fill_color(255, 255, 255)
            for ci in range(col_count):
                cell = strip_md_inline(row[ci]) if ci < len(row) else ""
                self.cell(col_w, line_h, cell, border=1, fill=True)
            self.ln(line_h)
        self.set_x(self.l_margin)
        self.ln(2)


def parse_table_row(line: str) -> list[str] | None:
    if not line.strip().startswith("|"):
        return None
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    if all(re.fullmatch(r":?-+:?", p) for p in parts):
        return None
    return parts


def image_path_from_md(line: str, base: Path) -> Path | None:
    m = re.search(r"!\[([^\]]*)\]\(([^)]+)\)", line)
    if not m:
        return None
    rel = m.group(2).split("?")[0]
    return (base / rel).resolve()


def build_pdf(md_path: Path, pdf_path: Path, *, enable_links: bool = False) -> None:
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    base = md_path.parent

    font_path = find_font()
    pdf = GuidePDF(font_path, enable_links=enable_links)
    pdf.add_page()

    in_code = False
    code_buf: list[str] = []
    table_buf: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_buf
        if table_buf:
            pdf.add_table(table_buf)
            table_buf = []

    for raw in lines:
        line = raw.rstrip()

        if in_code:
            if line.strip().startswith("```"):
                pdf.add_code_block(code_buf)
                code_buf = []
                in_code = False
            else:
                code_buf.append(line)
            continue

        if line.strip().startswith("```"):
            flush_table()
            in_code = True
            code_buf = []
            continue

        row = parse_table_row(line)
        if row is not None:
            table_buf.append(row)
            continue
        flush_table()

        if not line.strip():
            pdf.ln(2)
            continue

        if line.strip() == "---":
            pdf.add_hr()
            continue

        img = image_path_from_md(line, base)
        if img:
            caption_m = re.search(r"!\[([^\]]*)\]", line)
            caption = caption_m.group(1) if caption_m and caption_m.group(1) else ""
            pdf.add_image_block(img, caption)
            continue

        toc_m = TOC_ITEM_RE.match(line.strip())
        if toc_m and enable_links:
            pdf.add_toc_item(toc_m.group(1), toc_m.group(2), toc_m.group(3))
            continue

        if line.startswith("# "):
            title = line[2:].strip()
            pdf.add_title(title, 1, anchor=heading_anchor(title) if enable_links else None)
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            anchor = heading_anchor(title) if enable_links and re.match(r"^\d+\.", title) else None
            if anchor is None and enable_links and title == "目錄":
                anchor = heading_anchor(title)
            pdf.add_title(title, 2, anchor=anchor)
            continue
        if line.startswith("### "):
            title = line[4:].strip()
            anchor = heading_anchor(title) if enable_links else None
            pdf.add_title(title, 3, anchor=anchor)
            continue

        if line.startswith("- [ ] ") or line.startswith("- [x] "):
            mark = "[x]" if line[3:6] == "[x]" else "[ ]"
            pdf.add_bullet(f"{mark} {line[6:].strip()}")
            continue
        if line.startswith("- "):
            pdf.add_bullet(line[2:].strip())
            continue

        num_m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if num_m:
            pdf.add_numbered(f"{num_m.group(1)}.", num_m.group(2))
            continue

        if line.startswith(">"):
            pdf.add_paragraph(line.lstrip("> ").strip())
            continue

        pdf.add_paragraph(line)

    flush_table()
    if in_code and code_buf:
        pdf.add_code_block(code_buf)

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(pdf_path))


def main() -> int:
    if not MD_PATH.exists():
        print(f"Missing {MD_PATH}")
        return 1
    build_pdf(MD_PATH, PDF_PATH, enable_links=False)
    print(f"Wrote {PDF_PATH}")
    print(f"  size: {PDF_PATH.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
