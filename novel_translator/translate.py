from __future__ import annotations

import re
from typing import Callable

import httpx

from .google_draft import google_translate
from .library import _has_japanese, _looks_english, apply_glossary, glossary_resolve, strip_reading_parens
from .models import Novel

POLISH_PROMPT = """You are a copy editor for a novel translation.
The text below is a Google Translate draft from Japanese into {language}.
Rewrite it so grammar, punctuation, and flow read naturally.
Keep the same meaning, names, numbers, and paragraph breaks.
Do not invent a different title or different character names.
If a glossary is provided, use those official English spellings everywhere they apply.
Do not add romanization, furigana, pronunciation, or sound-effect spellings in parentheses.
Do not add commentary. Output only the revised text.
"""


def _strip_title_echo(title: str, text: str) -> str:
    lines = (text or "").splitlines()

    def is_echo(line: str) -> bool:
        raw = line.strip().lower().lstrip("# ").strip()
        if not raw:
            return True
        if raw == (title or "").strip().lower():
            return True
        if raw.startswith("chapter title:"):
            return True
        return False

    while lines and is_echo(lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip()


def _chat(client: httpx.Client, api_base: str, api_key: str, model: str, messages: list[dict]) -> str:
    if "11434" in api_base:
        response = client.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"temperature": 0.3, "num_predict": 8192},
            },
            timeout=600,
        )
        response.raise_for_status()
        data = response.json()
        text = (data.get("message") or {}).get("content") or ""
        if not text.strip():
            raise RuntimeError(f"Ollama returned an empty revision. Raw: {data!r}"[:800])
        return text.strip()

    url = api_base.rstrip("/") + "/chat/completions"
    response = client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "temperature": 0.3, "messages": messages},
        timeout=600,
    )
    response.raise_for_status()
    data = response.json()
    message = data["choices"][0]["message"]
    return (message.get("content") or "").strip()


def _polish(client: httpx.Client, api_base: str, api_key: str, model: str, language: str, draft: str, glossary: str) -> str:
    extra = f"\nIf a glossary is provided, keep those spellings.\nGlossary:\n{glossary}\n" if glossary.strip() else ""
    revised = _chat(
        client,
        api_base,
        api_key,
        model,
        [
            {"role": "system", "content": POLISH_PROMPT.format(language=language) + extra},
            {"role": "user", "content": draft},
        ],
    )
    cleaned = strip_reading_parens(revised or draft, draft)
    return apply_glossary(cleaned or draft, glossary)


def _draft_and_polish(
    client: httpx.Client,
    api_base: str,
    api_key: str,
    model: str,
    language: str,
    source: str,
    glossary: str,
) -> str:
    if not (source or "").strip():
        return ""
    if not _has_japanese(source):
        return apply_glossary(source, glossary)
    protected = apply_glossary(source, glossary)
    draft = google_translate(protected, language) if _has_japanese(protected) else protected
    draft = apply_glossary(draft, glossary)
    return _strip_title_echo("", _polish(client, api_base, api_key, model, language, draft, glossary) or draft)


def translate_novel(
    novel: Novel,
    api_key: str,
    api_base: str,
    model: str,
    language: str,
    glossary: str = "",
    progress: Callable[[str], None] | None = None,
    redo_translated: bool = False,
) -> Novel:
    if not model.strip():
        raise RuntimeError("Pick a model. For Ollama, start Ollama and click Refresh models.")
    if "openai.com" in api_base and not api_key.strip():
        raise RuntimeError("Cloud translation needs an API key. Use Ollama for a local model with no key.")
    if not api_key.strip():
        api_key = "ollama"
    log = progress or (lambda _msg: None)
    glossary = glossary or ""

    with httpx.Client() as client:
        if not novel.original_title:
            novel.original_title = novel.title
        if _has_japanese(novel.author) and not novel.original_author:
            novel.original_author = novel.author

        log("Google Translate: title...")
        novel.title = _draft_and_polish(
            client, api_base, api_key, model, language, novel.original_title, glossary
        )
        log(f"Title: {novel.title}")

        source_author = novel.original_author or novel.author
        official_author = glossary_resolve(source_author, glossary)
        if official_author:
            novel.author = official_author
            log(f"Official author: {novel.author}")
        elif source_author and not _looks_english(novel.author):
            log("Google Translate: author...")
            novel.author = google_translate(source_author, language) or source_author
            novel.author = apply_glossary(novel.author, glossary)
            log(f"Author: {novel.author}")

        if novel.synopsis:
            log("Google Translate: synopsis...")
            novel.synopsis = _draft_and_polish(
                client, api_base, api_key, model, language, novel.synopsis, glossary
            )

        for chapter in novel.chapters:
            if (chapter.translated_text or "").strip() and not redo_translated:
                log(f"Already translated chapter {chapter.number}: {chapter.title}")
                continue
            log(f"Google Translate: chapter {chapter.number}...")
            if not chapter.original_title and _has_japanese(chapter.title):
                chapter.original_title = chapter.title
            heading_src = chapter.original_title or chapter.title
            chapter.title = apply_glossary(heading_src, glossary)
            if _has_japanese(chapter.title):
                chapter.title = apply_glossary(
                    google_translate(heading_src, language) or heading_src, glossary
                )
            source = apply_glossary(chapter.source_text, glossary)
            draft = google_translate(source, language) if _has_japanese(source) else source
            draft = apply_glossary(draft, glossary)
            log(f"Polishing chapter {chapter.number} for grammar and flow...")
            polished = _polish(client, api_base, api_key, model, language, draft, glossary)
            chapter.translated_text = apply_glossary(
                strip_reading_parens(_strip_title_echo(chapter.title, polished or draft), draft),
                glossary,
            )
            log(f"Finished chapter {chapter.number}: {chapter.title}")
    return novel
