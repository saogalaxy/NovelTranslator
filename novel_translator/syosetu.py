from __future__ import annotations

import re
import time
from typing import Callable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .models import Chapter, Novel

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
NCODE_RE = re.compile(r"(n[0-9]{4,}[a-z]+)", re.I)
HOSTS = {
    "ncode.syosetu.com": "https://ncode.syosetu.com",
    "novel18.syosetu.com": "https://novel18.syosetu.com",
}


def novel_page_url(ncode: str, source_url: str = "") -> str:
    text = (source_url or "").strip()
    if text.startswith("http") and "syosetu.com" in text:
        return text if text.endswith("/") else text + "/"
    code = (ncode or "").strip().lower()
    if not code:
        return text
    host = "novel18.syosetu.com" if "novel18" in text else "ncode.syosetu.com"
    return f"https://{host}/{code}/"


def parse_ncode(value: str) -> tuple[str, str]:
    text = value.strip()
    host = "ncode.syosetu.com"
    if "novel18.syosetu.com" in text:
        host = "novel18.syosetu.com"
    match = NCODE_RE.search(text)
    if not match:
        raise ValueError("Could not find an ncode like n4830bu in that URL.")
    return match.group(1).lower(), host


def fetch_html(client: httpx.Client, url: str) -> str:
    response = client.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.text


def series_info(source: str) -> dict:
    ncode, _host = parse_ncode(source)
    meta = fetch_metadata(ncode)
    try:
        total = int(meta.get("general_all_no") or 0)
    except (TypeError, ValueError):
        total = 0
    return {
        "ncode": ncode,
        "title": meta.get("title") or ncode,
        "author": meta.get("writer") or "",
        "series_chapters": total,
        "last_update": meta.get("general_lastup") or "",
    }


def fetch_metadata(ncode: str) -> dict:
    url = "https://api.syosetu.com/novelapi/api/"
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        response = client.get(url, params={"ncode": ncode, "out": "json"})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list) or len(payload) < 2:
        return {}
    return payload[1]


def _ruby_to_text(node: Tag) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, Tag) and child.name == "rt":
            continue
        if isinstance(child, Tag) and child.name == "rp":
            continue
        if isinstance(child, Tag):
            parts.append(child.get_text())
        else:
            parts.append(str(child))
    return "".join(parts)


def paragraph_text(p: Tag) -> str:
    chunks: list[str] = []
    for child in p.children:
        if isinstance(child, Tag) and child.name == "ruby":
            chunks.append(_ruby_to_text(child))
        elif isinstance(child, Tag) and child.name == "br":
            chunks.append("\n")
        elif isinstance(child, Tag):
            chunks.append(child.get_text())
        else:
            chunks.append(str(child))
    return "".join(chunks).replace("\xa0", " ").strip()


def parse_chapter_html(html: str, url: str, number: int) -> Chapter:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one("h1.p-novel__title")
    title = title_el.get_text(strip=True) if title_el else f"Chapter {number}"
    body = soup.select_one("div.js-novel-text.p-novel__text:not(.p-novel__text--afterword)")
    if not body:
        body = soup.select_one("#novel_honbun")
    lines: list[str] = []
    if body:
        for p in body.find_all("p"):
            text = paragraph_text(p)
            lines.append(text)
    after = soup.select_one("div.p-novel__text--afterword")
    if after:
        after_lines = [paragraph_text(p) for p in after.find_all("p")]
        after_text = "\n".join(line for line in after_lines if line)
        if after_text:
            lines.append("")
            lines.append("[Author note]")
            lines.append(after_text)
    return Chapter(
        number=number,
        title=title,
        url=url,
        source_text="\n".join(lines).strip(),
        original_title=title,
    )


def _parse_toc_page(html: str, base: str) -> tuple[list[Chapter], str | None]:
    soup = BeautifulSoup(html, "lxml")
    chapters: list[Chapter] = []
    volume = ""
    listing = soup.select_one("div.p-eplist")
    if not listing:
        return chapters, None
    for child in listing.children:
        if not isinstance(child, Tag):
            continue
        classes = child.get("class") or []
        if "p-eplist__chapter-title" in classes:
            volume = child.get_text(strip=True)
            continue
        if "p-eplist__sublist" not in classes:
            continue
        link = child.select_one("a.p-eplist__subtitle")
        if not link:
            continue
        href = link.get("href") or ""
        match = re.search(r"/(\d+)/?$", href)
        number = int(match.group(1)) if match else len(chapters) + 1
        chapters.append(
            Chapter(
                number=number,
                title=link.get_text(strip=True),
                url=urljoin(base, href),
                volume=volume,
                original_title=link.get_text(strip=True),
            )
        )
    next_link = soup.select_one("a.c-pager__item--next")
    next_url = urljoin(base, next_link["href"]) if next_link and next_link.get("href") else None
    return chapters, next_url


def fetch_novel(
    source: str,
    start: int = 1,
    end: int | None = None,
    delay: float = 0.8,
    progress: Callable[[str], None] | None = None,
    existing: Novel | None = None,
    skip_download: set[int] | None = None,
) -> Novel:
    ncode, host = parse_ncode(source)
    base = HOSTS[host]
    index_url = f"{base}/{ncode}/"
    log = progress or (lambda _msg: None)
    meta = fetch_metadata(ncode)
    title = meta.get("title") or ncode
    author = meta.get("writer") or ""
    synopsis = meta.get("story") or ""

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=45) as client:
        log(f"Loading table of contents for {ncode}...")
        page_url: str | None = index_url
        seen: set[str] = set()
        toc: list[Chapter] = []
        index_html = ""
        while page_url and page_url not in seen:
            seen.add(page_url)
            html = fetch_html(client, page_url)
            if page_url.rstrip("/") == index_url.rstrip("/"):
                index_html = html
            page_chapters, page_url = _parse_toc_page(html, base)
            toc.extend(page_chapters)
            if page_url:
                time.sleep(delay)
        # Short novels put the full body on the index page with no /1/ TOC entry.
        if not toc and index_html:
            direct = parse_chapter_html(index_html, index_url, 1)
            if (direct.source_text or "").strip():
                log("Short novel: reading chapter text from the series page.")
                toc = [
                    Chapter(
                        number=1,
                        title=direct.title or title,
                        url=index_url,
                        source_text=direct.source_text,
                        original_title=direct.original_title or direct.title or title,
                    )
                ]
        if not toc:
            raise RuntimeError("No chapters found. The novel may require login or a different URL.")

        selected = [ch for ch in toc if ch.number >= start and (end is None or ch.number <= end)]
        if not selected:
            last = max(ch.number for ch in toc)
            raise RuntimeError(
                f"No chapters in range {start}–{end or 'end'}. This series only has {last} chapter(s)."
            )
        previous = {ch.number: ch for ch in (existing.chapters if existing else [])}
        skip = skip_download or set()
        to_fetch = [
            ch
            for ch in selected
            if ch.number not in skip
            or not (previous.get(ch.number) and previous[ch.number].source_text.strip())
        ]
        log(
            f"{len(selected)} chapter(s) in range, {len(to_fetch)} to download, "
            f"{len(selected) - len(to_fetch)} already on disk."
        )
        pending = list(to_fetch)
        for chapter in selected:
            old = previous.get(chapter.number)
            if old and chapter.number in skip and (old.source_text or "").strip():
                chapter.title = old.title or chapter.title
                chapter.original_title = old.original_title or chapter.original_title or chapter.title
                chapter.source_text = old.source_text
                chapter.translated_text = old.translated_text
                chapter.volume = old.volume or chapter.volume
                log(f"Already downloaded chapter {chapter.number}: {chapter.title}")
                continue
            if (chapter.source_text or "").strip():
                log(f"Using page text for chapter {chapter.number}: {chapter.title}")
                if old and (old.translated_text or "").strip():
                    chapter.translated_text = old.translated_text
                continue
            log(f"Downloading {chapter.number}: {chapter.title}")
            html = fetch_html(client, chapter.url)
            parsed = parse_chapter_html(html, chapter.url, chapter.number)
            chapter.title = parsed.title or chapter.title
            chapter.source_text = parsed.source_text
            if old and (old.translated_text or "").strip():
                chapter.translated_text = old.translated_text
            pending = [item for item in pending if item.number != chapter.number]
            if pending:
                time.sleep(delay)

    return Novel(
        ncode=ncode,
        title=title,
        author=author,
        synopsis=synopsis,
        source_url=index_url,
        chapters=selected,
        original_title=title,
    )
