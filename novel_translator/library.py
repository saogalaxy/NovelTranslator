from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .epub_export import english_filename
from .models import Chapter, Novel

INDEX_NAME = "library.json"

DEFAULT_GLOSSARY = ""


def parse_glossary(glossary: str) -> list[tuple[str, str]]:
    pairs = []
    for line in (glossary or "").splitlines():
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        ja, en = left.strip(), right.strip()
        if ja and en:
            pairs.append((ja, en))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def merge_glossary(user: str, extra: str = "") -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for ja, en in parse_glossary(user) + parse_glossary(DEFAULT_GLOSSARY) + parse_glossary(extra):
        if ja in seen:
            continue
        seen.add(ja)
        lines.append(f"{ja} = {en}")
    return "\n".join(lines)


def _fold_jp(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", text or "")


def glossary_resolve(text: str, glossary: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    folded = _fold_jp(raw)
    pairs = parse_glossary(glossary)
    for ja, en in pairs:
        if raw == ja or raw == en or folded == _fold_jp(ja) or folded == _fold_jp(en):
            return en
    contained = [(ja, en) for ja, en in pairs if ja and (_fold_jp(ja) in folded or ja in raw)]
    if not contained:
        return ""
    starts = [item for item in contained if folded.startswith(_fold_jp(item[0])) or raw.startswith(item[0])]
    best = max(starts or contained, key=lambda item: len(_fold_jp(item[0])))
    return best[1]


def expand_glossary_aliases(glossary: str) -> str:
    """Add Google's English guesses so they can be rewritten to official spellings."""
    from .google_draft import google_translate

    extra: list[str] = []
    seen = {ja for ja, _en in parse_glossary(glossary)}
    for ja, en in parse_glossary(glossary):
        if not _has_japanese(ja):
            continue
        try:
            guess = (google_translate(ja, "English") or "").strip()
        except Exception:
            guess = ""
        if guess and guess != en and guess not in seen:
            extra.append(f"{guess} = {en}")
            seen.add(guess)
    return (glossary or "").strip() + (("\n" + "\n".join(extra)) if extra else "")


def apply_official_names(novel: Novel, glossary: str) -> bool:
    gloss = expand_glossary_aliases(glossary)
    pairs = parse_glossary(gloss)
    changed = False
    if novel.title:
        next_title = apply_glossary(novel.title, gloss)
        if next_title != novel.title:
            novel.title = next_title
            changed = True
    if novel.author:
        next_author = apply_glossary(novel.author, gloss)
        if next_author != novel.author:
            novel.author = next_author
            changed = True
    if novel.synopsis:
        next_syn = apply_glossary(novel.synopsis, gloss)
        if next_syn != novel.synopsis:
            novel.synopsis = next_syn
            changed = True
    for chapter in novel.chapters:
        if chapter.title:
            nxt = apply_glossary(chapter.title, gloss)
            if nxt != chapter.title:
                chapter.title = nxt
                changed = True
        if chapter.translated_text:
            nxt = apply_glossary(chapter.translated_text, gloss)
            nxt = _align_names_from_source(chapter.source_text, nxt, pairs)
            nxt = strip_reading_parens(nxt)
            if nxt != chapter.translated_text:
                chapter.translated_text = nxt
                changed = True
    return changed


def _align_names_from_source(source: str, translated: str, pairs: list[tuple[str, str]]) -> str:
    text = translated or ""
    folded_src = _fold_jp(source)
    for ja, en in pairs:
        if not ja or not en or not _has_japanese(ja):
            continue
        if len(en.split()) < 2:
            continue
        if _fold_jp(ja) not in folded_src:
            continue
        if en in text:
            continue
        updated, count = re.subn(
            r"(?<![A-Za-z])[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)(?![A-Za-z])",
            en,
            text,
            count=1,
        )
        if count:
            return updated
    return text


_READING_PAREN = re.compile(r"\s*\(([^)]{1,120})\)")
_READING_PARTICLES = {
    "ni", "no", "wo", "ga", "to", "wa", "mo", "de", "nara", "demo", "kara", "made",
    "desu", "da", "na", "yo", "ne",
}


def strip_reading_parens(text: str, keep_from: str = "") -> str:
    kept = set(_READING_PAREN.findall(keep_from or ""))

    def replace(match: re.Match[str]) -> str:
        inner = (match.group(1) or "").strip()
        if inner in kept:
            return match.group(0)
        if _has_japanese(inner):
            return ""
        words = re.findall(r"[A-Za-z]+", inner)
        if not words:
            return match.group(0)
        particles = sum(1 for word in words if word.lower() in _READING_PARTICLES)
        if particles >= 2:
            return ""
        if len(words) <= 4 and not any(word.lower() in {"the", "and", "of", "a", "to"} for word in words):
            return ""
        return match.group(0)

    return re.sub(r" {2,}", " ", _READING_PAREN.sub(replace, text or "")).strip()


def apply_glossary(text: str, glossary: str) -> str:
    result = text or ""
    for ja, en in parse_glossary(glossary):
        if not ja or not en:
            continue
        result = result.replace(ja, en)
        folded = _fold_jp(ja)
        if folded and folded != ja:
            pattern = r"[\s\u3000]*".join(re.escape(ch) for ch in folded)
            result = re.sub(pattern, en, result)
    return result


def _looks_english(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    ascii_letters = [ch for ch in letters if ch.isascii()]
    return len(ascii_letters) / len(letters) >= 0.8


def _has_japanese(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text or ""))


def display_author(author: str, glossary: str = "", original: str = "", ncode: str = "") -> str:
    glossary = merge_glossary(glossary)
    english = ""
    if _looks_english(author) and not _has_japanese(author):
        english = author.strip()
    if not english:
        for candidate in (original, author):
            hit = glossary_resolve(candidate, glossary)
            if hit:
                english = hit
                break
    japanese = ""
    for candidate in (original, author):
        if _has_japanese(candidate):
            japanese = candidate.strip()
            break
    if english and japanese:
        return f"{english} ({japanese})"
    return english or japanese or (author or original or "").strip()


def display_book_title(title: str, ncode: str, glossary: str = "", original: str = "") -> str:
    glossary = merge_glossary(glossary)
    hit = glossary_resolve(original or title, glossary)
    if hit:
        return hit
    if _looks_english(title):
        return title.strip()
    cleaned = english_filename(title or "", fallback="")
    if cleaned:
        return cleaned
    return ncode or "Untitled book"


def chapter_pair(title: str, original: str = "", glossary: str = "") -> tuple[str, str]:
    japanese = clean_chapter_title(original, 0)
    english = clean_chapter_title(title, 0)
    if _has_japanese(english) and not japanese:
        japanese, english = english, ""
    if japanese and english and japanese == english:
        english = ""
    if _has_japanese(english):
        english = ""
    if japanese and not english:
        mapped = apply_glossary(japanese, glossary)
        if mapped and mapped != japanese and not _has_japanese(mapped):
            english = clean_chapter_title(mapped, 0)
    return japanese, english


def chapter_entry(number: int, title: str, translated: bool, original: str = "", glossary: str = "") -> dict:
    japanese, english = chapter_pair(title, original, glossary)
    return {
        "number": number,
        "japanese": japanese,
        "english": english,
        "status": "translated" if translated else "downloaded",
    }


def chapter_label(number: int, title: str, translated: bool, original: str = "") -> str:
    row = chapter_entry(number, title, translated, original)
    mark = row["status"]
    if row["japanese"] and row["english"]:
        return f"Chapter {number}: {row['japanese']} / {row['english']}  [{mark}]"
    name = row["english"] or row["japanese"]
    if name:
        return f"Chapter {number}: {name}  [{mark}]"
    return f"Chapter {number}  [{mark}]"


def fill_english_chapter_titles(novel: Novel, glossary: str = "") -> bool:
    from .google_draft import google_translate

    changed = False
    for chapter in novel.chapters:
        if not chapter.original_title and _has_japanese(chapter.title):
            chapter.original_title = chapter.title
            changed = True
        japanese, english = chapter_pair(chapter.title, chapter.original_title, glossary)
        if japanese and not english:
            try:
                english = apply_glossary(google_translate(japanese, "English") or "", glossary)
            except Exception:
                english = ""
            english = clean_chapter_title(english, chapter.number)
            if english and _has_japanese(english):
                english = ""
        if english and chapter.title != english:
            chapter.title = english
            changed = True
        if japanese and chapter.original_title != japanese:
            chapter.original_title = japanese
            changed = True
    return changed


def clean_chapter_title(title: str, number: int = 0) -> str:
    name = (title or "").strip()
    name = re.sub(r"^(chapter\s*title\s*:)\s*", "", name, flags=re.I)
    name = re.sub(r"^chapter\s+\d+\s*:\s*", "", name, flags=re.I)
    return name.strip() or (f"Chapter {number}" if number else "")


def library_root(output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def book_dir(output_dir: str | Path, ncode: str) -> Path:
    path = library_root(output_dir) / "books" / ncode
    path.mkdir(parents=True, exist_ok=True)
    return path


def book_json_path(output_dir: str | Path, ncode: str) -> Path:
    return book_dir(output_dir, ncode) / "book.json"


def novel_from_dict(data: dict) -> Novel:
    chapters = [Chapter(**item) for item in data.get("chapters") or []]
    return Novel(
        ncode=data.get("ncode") or "",
        title=data.get("title") or "",
        author=data.get("author") or "",
        synopsis=data.get("synopsis") or "",
        source_url=data.get("source_url") or "",
        chapters=chapters,
        original_title=data.get("original_title") or "",
        original_author=data.get("original_author") or "",
    )


def save_novel(output_dir: str | Path, novel: Novel, epub_path: str | Path | None = None) -> Path:
    path = book_json_path(output_dir, novel.ncode or english_filename(novel.title, "book"))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(novel)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    upsert_index(output_dir, novel, epub_path=epub_path, book_json=path)
    return path


def load_novel(path: str | Path) -> Novel:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return novel_from_dict(data)


def load_index(output_dir: str | Path) -> list[dict]:
    index_path = library_root(output_dir) / INDEX_NAME
    if not index_path.exists():
        return []
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("books") or [])
    if isinstance(data, list):
        return data
    return []


def upsert_index(
    output_dir: str | Path,
    novel: Novel,
    epub_path: str | Path | None = None,
    book_json: str | Path | None = None,
) -> None:
    books = load_index(output_dir)
    previous = next((item for item in books if item.get("ncode") == novel.ncode), None)
    if previous and previous.get("epub") and not epub_path:
        epub_path = previous["epub"]
    translated = sum(1 for ch in novel.chapters if ch.translated_text.strip())
    downloaded = sum(1 for ch in novel.chapters if ch.source_text.strip())
    status = "translated" if translated else "downloaded"
    entry = {
        "ncode": novel.ncode,
        "title": novel.title,
        "original_title": novel.original_title or novel.title,
        "author": novel.author,
        "original_author": novel.original_author or novel.author,
        "status": status,
        "downloaded": downloaded,
        "translated": translated,
        "total": len(novel.chapters),
        "epub": str(epub_path) if epub_path else "",
        "book_json": str(book_json or book_json_path(output_dir, novel.ncode)),
        "source_url": novel.source_url or "",
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    books = [item for item in books if item.get("ncode") != novel.ncode]
    books.insert(0, entry)
    (library_root(output_dir) / INDEX_NAME).write_text(
        json.dumps({"books": books}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def merge_existing_work(fresh: Novel, existing: Novel | None, replace_translations: bool) -> tuple[Novel, int]:
    if not existing:
        return fresh, 0
    if existing.original_title and not fresh.original_title:
        fresh.original_title = existing.original_title
    if existing.original_author and not fresh.original_author:
        fresh.original_author = existing.original_author
    gloss = merge_glossary("")
    title_hit = glossary_resolve(fresh.original_title or fresh.title or existing.original_title, gloss)
    author_hit = glossary_resolve(fresh.original_author or fresh.author or existing.original_author, gloss)
    if title_hit:
        fresh.title = title_hit
    elif _looks_english(existing.title):
        fresh.title = existing.title
    if author_hit:
        fresh.author = author_hit
    elif _looks_english(existing.author):
        fresh.author = existing.author
    if existing.synopsis and _looks_english(existing.synopsis) and not _looks_english(fresh.synopsis):
        fresh.synopsis = existing.synopsis
    if replace_translations:
        return fresh, 0
    previous = {ch.number: ch for ch in existing.chapters}
    kept = 0
    for chapter in fresh.chapters:
        old = previous.get(chapter.number)
        if not old or not (old.translated_text or "").strip():
            continue
        chapter.translated_text = old.translated_text
        if old.original_title and not chapter.original_title:
            chapter.original_title = old.original_title
        elif old.title and _has_japanese(old.title) and not chapter.original_title:
            chapter.original_title = old.title
        if old.title and (_looks_english(old.title) or not chapter.title):
            chapter.title = old.title
        kept += 1
    return fresh, kept


def existing_novel(output_dir: str | Path, ncode: str) -> Novel | None:
    path = book_json_path(output_dir, ncode)
    if path.exists():
        return load_novel(path)
    return None


def plan_range(existing: Novel | None, start: int, end: int | None) -> dict:
    downloaded: list[int] = []
    translated: list[int] = []
    if not existing:
        return {"downloaded": downloaded, "translated": translated}
    for chapter in existing.chapters:
        number = chapter.number
        if number < start or (end is not None and number > end):
            continue
        if (chapter.source_text or "").strip():
            downloaded.append(number)
        if (chapter.translated_text or "").strip():
            translated.append(number)
    return {"downloaded": downloaded, "translated": translated}


def union_chapters(base: Novel | None, incoming: Novel) -> Novel:
    by_number = {ch.number: ch for ch in (base.chapters if base else [])}
    for chapter in incoming.chapters:
        by_number[chapter.number] = chapter
    incoming.chapters = [by_number[n] for n in sorted(by_number)]
    return incoming


def translated_count(novel: Novel | None) -> int:
    if not novel:
        return 0
    return sum(1 for ch in novel.chapters if (ch.translated_text or "").strip())


def discover_epubs(output_dir: str | Path) -> list[Path]:
    root = library_root(output_dir)
    return sorted(root.glob("*.epub")) + sorted((root / "books").glob("*/*.epub"))
