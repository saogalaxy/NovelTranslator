from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chapter:
    number: int
    title: str
    url: str
    volume: str = ""
    source_text: str = ""
    translated_text: str = ""
    original_title: str = ""


@dataclass
class Novel:
    ncode: str
    title: str
    author: str
    synopsis: str
    source_url: str
    chapters: list[Chapter] = field(default_factory=list)
    original_title: str = ""
    original_author: str = ""
