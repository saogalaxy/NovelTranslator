from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from .models import Chapter, Novel


def import_pdf(path: str | Path) -> Novel:
    pdf_path = Path(path)
    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text.strip())
    body = "\n\n".join(part for part in pages if part)
    if not body.strip():
        raise RuntimeError(
            "No text could be extracted from that PDF. "
            "Syosetu vertical PDFs often have no selectable text; use the novel URL instead."
        )
    meta = reader.metadata or {}
    title = str(meta.get("/Title") or pdf_path.stem)
    author = str(meta.get("/Author") or "")
    chapter = Chapter(number=1, title=title, url=str(pdf_path), source_text=body)
    return Novel(
        ncode=pdf_path.stem,
        title=title,
        author=author,
        synopsis="",
        source_url=str(pdf_path),
        chapters=[chapter],
    )
