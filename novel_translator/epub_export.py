from __future__ import annotations

import html
import re
from pathlib import Path

from ebooklib import epub

from .models import Novel


def _heading(title: str) -> str:
    name = (title or "").strip()
    name = re.sub(r"^(chapter\s*title\s*:)\s*", "", name, flags=re.I)
    name = re.sub(r"^chapter\s+\d+\s*:\s*", "", name, flags=re.I)
    return name.strip() or title or "Chapter"


def _without_title(title: str, body: str) -> str:
    lines = (body or "").splitlines()
    needle = (title or "").strip().lower()
    while lines:
        raw = lines[0].strip().lower().lstrip("# ")
        if not raw or raw == needle or raw.startswith("chapter title:"):
            lines.pop(0)
            continue
        break
    return "\n".join(lines).strip()


def _to_xhtml(title: str, body: str) -> bytes:
    heading = _heading(title)
    body = _without_title(heading, body)
    paragraphs = []
    for block in re.split(r"\n\s*\n", (body or "").strip()):
        lines = "<br/>".join(html.escape(line) for line in block.splitlines())
        if lines:
            paragraphs.append(f"<p>{lines}</p>")
    inner = "\n".join(paragraphs) or "<p></p>"
    html_doc = (
        "<html><head><title>"
        + html.escape(heading)
        + "</title></head><body><h1>"
        + html.escape(heading)
        + f"</h1>{inner}</body></html>"
    )
    return html_doc.encode("utf-8")


def english_filename(title: str, fallback: str = "translated-novel") -> str:
    cleaned = []
    for ch in title:
        if ch.isascii() and (ch.isalnum() or ch in " -_"):
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    name = " ".join("".join(cleaned).split()).strip(" ._")[:80]
    if not name or not any(c.isalpha() for c in name):
        return fallback
    return name


def export_epub(novel: Novel, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()
    book.set_identifier(f"novel-translator-{novel.ncode}")
    book.set_title(novel.title)
    book.set_language("en")
    if novel.author:
        book.add_author(novel.author)

    spine: list = ["nav"]
    toc = []
    if novel.synopsis:
        intro = epub.EpubHtml(title="Synopsis", file_name="synopsis.xhtml", lang="en")
        intro.content = _to_xhtml("Synopsis", novel.synopsis)
        book.add_item(intro)
        spine.append(intro)
        toc.append(intro)

    current_volume = None
    volume_section: list = []
    for chapter in novel.chapters:
        body = chapter.translated_text or chapter.source_text
        item = epub.EpubHtml(
            title=chapter.title,
            file_name=f"chapter-{chapter.number:04d}.xhtml",
            lang="en",
        )
        item.content = _to_xhtml(chapter.title, body)
        book.add_item(item)
        spine.append(item)
        if chapter.volume and chapter.volume != current_volume:
            if volume_section and current_volume:
                toc.append((epub.Section(current_volume), volume_section))
            current_volume = chapter.volume
            volume_section = [item]
        elif chapter.volume:
            volume_section.append(item)
        else:
            toc.append(item)
    if volume_section and current_volume:
        toc.append((epub.Section(current_volume), volume_section))

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book, {"epub3_pages": False})
    return path
