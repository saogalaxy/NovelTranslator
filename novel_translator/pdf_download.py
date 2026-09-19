from __future__ import annotations

from pathlib import Path
from typing import Callable

import httpx

from .syosetu import USER_AGENT, parse_ncode


def official_pdf_url(ncode: str) -> str:
    return f"https://pdfnovels.net/{ncode.lower()}/main.pdf"


def _looks_like_pdf(content: bytes, content_type: str) -> bool:
    if content.startswith(b"%PDF"):
        return True
    return "pdf" in (content_type or "").lower()


def download_official_pdf(
    source: str,
    dest_dir: str | Path,
    progress: Callable[[str], None] | None = None,
) -> Path:
    ncode, host = parse_ncode(source)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{ncode}.pdf"
    log = progress or (lambda _msg: None)
    headers = {"User-Agent": USER_AGENT, "Referer": f"https://{host}/{ncode}/"}
    errors: list[str] = []

    with httpx.Client(headers=headers, timeout=120, follow_redirects=True) as client:
        form_url = f"https://{host}/novelpdf/creatingpdf/ncode/{ncode}/"
        log(f"Requesting Syosetu PDF page for {ncode}...")
        try:
            response = client.post(form_url)
            if _looks_like_pdf(response.content, response.headers.get("content-type", "")):
                path.write_bytes(response.content)
                log(f"Saved PDF to {path}")
                return path
            errors.append(f"PDF form returned {response.status_code} {response.headers.get('content-type')}")
        except httpx.HTTPError as exc:
            errors.append(f"PDF form failed: {exc}")

        url = official_pdf_url(ncode)
        log(f"Trying {url}")
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                chunks = b"".join(response.iter_bytes())
            if _looks_like_pdf(chunks, response.headers.get("content-type", "")):
                path.write_bytes(chunks)
                log(f"Saved PDF to {path}")
                return path
            errors.append("pdfnovels.net did not return a PDF file")
        except httpx.HTTPError as exc:
            errors.append(f"pdfnovels.net failed: {exc}")

    raise RuntimeError(
        "Could not download the official vertical PDF. "
        + " ".join(errors)
        + " Use Novel chapters instead — that page is only a form, not a direct file link."
    )
