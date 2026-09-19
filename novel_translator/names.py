from __future__ import annotations

import re
from functools import lru_cache

from .models import Novel

_KATAKANA = re.compile(r"[ァ-ヴー]{2,8}")
_SKIP_KATA = {
    "スキル",
    "レベル",
    "ステータス",
    "アイテム",
    "ダンジョン",
    "クエスト",
    "ポイント",
    "システム",
    "ページ",
    "チェック",
}


@lru_cache(maxsize=1)
def _kakasi():
    from pykakasi import kakasi

    return kakasi()


def _cap(word: str) -> str:
    text = (word or "").strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def romanize(text: str) -> str:
    if not (text or "").strip():
        return ""
    parts = []
    for item in _kakasi().convert(text):
        orig = (item.get("orig") or "").strip()
        hepburn = (item.get("hepburn") or "").strip()
        if not orig or orig in "　・=／/":
            continue
        if hepburn:
            parts.append(hepburn)
    return " ".join(parts).strip()


def person_name_from_kana(reading: str) -> str:
    words = [_cap(part) for part in romanize(reading).split() if part]
    if len(words) >= 2:
        return f"{' '.join(words[1:])} {words[0]}"
    return " ".join(words)


def person_name(japanese: str, reading: str = "") -> str:
    if reading.strip():
        return person_name_from_kana(reading)
    return person_name_from_kana(japanese)


def extract_katakana_names(*texts: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for token in _KATAKANA.findall(text or ""):
            if token in seen or token in _SKIP_KATA:
                continue
            seen.add(token)
            found.append(token)
    return found


def parse_reading_table(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in (raw or "").splitlines():
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        written, reading = left.strip(), right.strip()
        if written and reading and re.search(r"[ぁ-んァ-ヴー]", reading):
            pairs.append((written, reading))
    return pairs


def harvest_prompt(sample: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "List personal names in the Japanese text. "
                "One name per line as: written = hiragana. "
                "Put a space between family name and given name in the hiragana. "
                "No romaji, no explanations, no places, no items."
            ),
        },
        {"role": "user", "content": sample[:5000]},
    ]


def glossary_from_readings(pairs: list[tuple[str, str]]) -> str:
    lines = []
    for written, reading in pairs:
        english = person_name_from_kana(reading)
        if english:
            lines.append(f"{written} = {english}")
    return "\n".join(lines)


def auto_name_glossary(novel: Novel, harvested: str = "") -> str:
    lines: list[str] = []
    if harvested:
        lines.append(harvested)
    blobs = [novel.synopsis or ""]
    for chapter in novel.chapters:
        blobs.append(chapter.title or "")
        blobs.append(chapter.source_text or "")
    for kata in extract_katakana_names(*blobs):
        english = " ".join(_cap(part) for part in romanize(kata).split())
        if english:
            lines.append(f"{kata} = {english}")
    return "\n".join(lines)


def name_sample(novel: Novel) -> str:
    parts = [
        f"Title: {novel.original_title or novel.title}",
        f"Author: {novel.original_author or novel.author}",
        novel.synopsis or "",
    ]
    for chapter in novel.chapters[:2]:
        parts.append(chapter.title or "")
        parts.append((chapter.source_text or "")[:1800])
    return "\n".join(parts)


def _ascii_name(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    return all(ch.isascii() for ch in letters)
