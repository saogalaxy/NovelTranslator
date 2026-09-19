from __future__ import annotations

import re

import httpx

_LANG = {
    "english": "en",
    "en": "en",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "portuguese": "pt",
    "italian": "it",
    "korean": "ko",
    "chinese": "zh-CN",
}


def language_code(name: str) -> str:
    return _LANG.get((name or "english").strip().lower(), "en")


def google_translate(text: str, target_language: str = "English", source: str = "ja") -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    dest = language_code(target_language)
    chunks = _chunks(raw, 4500)
    parts = [_translate_chunk(chunk, source, dest) for chunk in chunks]
    return "\n\n".join(part for part in parts if part).strip()


def _chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    blocks = re.split(r"\n\s*\n", text)
    out: list[str] = []
    buf = ""
    for block in blocks:
        if buf and len(buf) + len(block) + 2 > limit:
            out.append(buf)
            buf = block
        else:
            buf = f"{buf}\n\n{block}" if buf else block
    if buf:
        out.append(buf)
    return out


def _translate_chunk(text: str, source: str, dest: str) -> str:
    response = httpx.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": source, "tl": dest, "dt": "t", "q": text},
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    data = response.json()
    pieces = []
    for item in data[0] or []:
        if item and item[0]:
            pieces.append(item[0])
    return "".join(pieces).strip()
