from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
MU_SEARCH = "https://api.mangaupdates.com/v1/series/search"
MU_SERIES = "https://api.mangaupdates.com/v1/series/{sid}"
JIKAN_MANGA = "https://api.jikan.moe/v4/manga"
JIKAN_ANIME = "https://api.jikan.moe/v4/anime"
JIKAN_CHARS = "https://api.jikan.moe/v4/manga/{mid}/characters"
NU_SEARCH = "https://www.novelupdates.com/"
FANDOM_SEARCH = "https://community.fandom.com/api.php"

_HEADERS = {
    "User-Agent": "NovelTranslator/1.0 (desktop library helper)",
    "Accept": "application/json, text/html",
}


class _Client:
    """HTTP helper that permanently skips a host after a 403."""

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=20, headers=_HEADERS, follow_redirects=True)
        self.blocked: set[str] = set()

    def close(self) -> None:
        self._http.close()

    def _host(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _send(self, method: str, url: str, **kwargs) -> httpx.Response | None:
        host = self._host(url)
        if host in self.blocked:
            return None
        try:
            response = self._http.request(method, url, **kwargs)
        except httpx.HTTPError:
            return None
        if response.status_code == 403:
            self.blocked.add(host)
            return None
        if response.status_code >= 400:
            return None
        return response

    def get(self, url: str, **kwargs) -> httpx.Response | None:
        return self._send("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response | None:
        return self._send("POST", url, **kwargs)

    def json(self, method: str, url: str, **kwargs) -> Any:
        response = self._send(method, url, **kwargs)
        if response is None:
            return None
        try:
            return response.json()
        except ValueError:
            return None


def lookup_official(
    japanese_title: str,
    english_title: str = "",
    author: str = "",
    model: str = "",
    ollama_key: str = "",
) -> dict[str, Any]:
    queries = _search_queries(japanese_title, english_title)
    official_title = ""
    native_title = (japanese_title or "").strip()
    names: list[dict[str, str]] = []
    publishers: list[str] = []
    available: list[str] = []
    links: list[dict[str, str]] = []
    author_en = ""
    summary = ""

    client = _Client()
    try:
        wiki = _wikipedia(client, queries)
        if wiki:
            official_title = wiki.get("title") or official_title
            summary = wiki.get("extract") or ""
            _add_link(links, "Wikipedia", wiki.get("url") or "")
            _merge_media(available, summary)
            _merge_pubs(publishers, summary)
            if not author_en:
                author_en = _author_from_text(summary)
            native = _native_from_text(summary)
            if native:
                native_title = native
            _merge_names(names, _wiki_characters(client, official_title or wiki.get("title") or ""))

        extra = [official_title] if official_title else []
        mu = _mangaupdates(client, queries + extra)
        if mu:
            official_title = official_title or mu.get("title") or ""
            author_en = author_en or mu.get("author") or ""
            _merge_list(available, mu.get("available") or [])
            _merge_list(publishers, mu.get("publishers") or [])
            _merge_names(names, mu.get("names") or [])
            _add_link(links, "MangaUpdates", mu.get("url") or "")

        jikan = _jikan(client, queries + extra)
        if jikan:
            official_title = official_title or jikan.get("title") or ""
            author_en = author_en or jikan.get("author") or ""
            _merge_list(available, jikan.get("available") or [])
            _merge_list(publishers, jikan.get("publishers") or [])
            _merge_names(names, jikan.get("names") or [])
            for link in jikan.get("links") or []:
                _add_link(links, link.get("label") or "", link.get("url") or "")

        nu = _novelupdates(client, queries + extra)
        if nu:
            official_title = official_title or nu.get("title") or ""
            _merge_list(available, nu.get("available") or [])
            _merge_list(publishers, nu.get("publishers") or [])
            _add_link(links, "Novel Updates", nu.get("url") or "")

        fandom = _fandom(client, official_title or (queries[0] if queries else ""))
        if fandom:
            _add_link(links, "Fandom wiki", fandom.get("url") or "")
            _merge_pubs(publishers, fandom.get("extract") or "")
            _merge_media(available, fandom.get("extract") or "")
            _merge_names(names, fandom.get("names") or [])
        if official_title:
            _merge_names(names, _fandom_characters(client, official_title))
    finally:
        client.close()

    if model:
        from novel_translator.ollama_web import lookup_with_ollama

        web = lookup_with_ollama(japanese_title, english_title, author, model, ollama_key)
        if web:
            official_title = official_title or web.get("official_title") or ""
            author_en = author_en or web.get("author_english") or ""
            _merge_list(available, web.get("available") or [])
            _merge_list(publishers, web.get("publishers") or [])
            _merge_names(names, web.get("names") or [])
            for link in web.get("links") or []:
                _add_link(links, link.get("label") or "Web", link.get("url") or "")
            if not summary:
                summary = web.get("summary") or ""

    found = bool(official_title or available or names or publishers)
    return {
        "found": found,
        "official_title": official_title,
        "native_title": native_title,
        "author_english": author_en or author,
        "available": available,
        "publishers": publishers,
        "names": names,
        "links": links,
        "summary": summary,
    }


def enrich_official_names(info: dict[str, Any]) -> dict[str, Any]:
    title = (info.get("official_title") or "").strip()
    if not title:
        return info
    names = list(info.get("names") or [])
    client = _Client()
    try:
        _merge_names(names, _wiki_characters(client, title))
        _merge_names(names, _fandom_characters(client, title))
        _merge_names(names, _names_from_markup(info.get("summary") or ""))
    finally:
        client.close()
    info["names"] = names
    return info


def official_glossary(info: dict[str, Any], original_author: str = "") -> str:
    lines = []
    native = (info.get("native_title") or "").strip()
    official = (info.get("official_title") or "").strip()
    if native and official:
        lines.append(f"{native} = {official}")
    author_en = (info.get("author_english") or "").strip()
    ja_author = (original_author or "").strip()
    if ja_author and author_en and author_en != ja_author:
        lines.append(f"{ja_author} = {author_en}")
        compact = re.sub(r"[\s\u3000]+", "", ja_author)
        if compact and compact != ja_author:
            lines.append(f"{compact} = {author_en}")
    for pair in info.get("names") or []:
        ja, en = (pair.get("native") or "").strip(), (pair.get("english") or "").strip()
        if ja and en:
            lines.append(f"{ja} = {en}")
            compact = re.sub(r"[\s\u3000]+", "", ja)
            if compact and compact != ja:
                lines.append(f"{compact} = {en}")
    return "\n".join(lines)


def describe_official(info: dict[str, Any]) -> str:
    if not info.get("found"):
        return "No official book, manga, or anime listing found."
    bits = []
    if info.get("official_title"):
        bits.append(f"Official title: {info['official_title']}")
    if info.get("author_english"):
        bits.append(f"Listed creator: {info['author_english']}")
    if info.get("available"):
        bits.append("Available as: " + ", ".join(info["available"]))
    if info.get("publishers"):
        bits.append("Publishers mentioned: " + ", ".join(info["publishers"]))
    return " | ".join(bits)


def _search_queries(*titles: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for title in titles:
        raw = (title or "").strip()
        if not raw:
            continue
        parts = [raw, re.split(r"[～〜~]", raw, 1)[0].strip()]
        for part in parts:
            if part and part not in seen:
                seen.add(part)
                out.append(part)
    return out


def _wikipedia(client: _Client, queries: list[str]) -> dict:
    for query in queries:
        search = client.json(
            "GET",
            WIKI_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": f"{query} (novel OR manga OR anime OR light)",
                "srlimit": 1,
                "format": "json",
            },
        )
        hits = ((search or {}).get("query") or {}).get("search") or []
        if not hits:
            continue
        title = hits[0].get("title") or ""
        summary = client.json("GET", WIKI_SUMMARY.format(title=title.replace(" ", "_"))) or {}
        page_title = summary.get("title") or title
        extract = _wiki_plain(client, page_title) or (summary.get("extract") or "")
        if not _related(query, page_title, extract):
            continue
        url = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
        if not url:
            url = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"
        return {"title": page_title, "extract": extract, "url": url}
    return {}


def _wiki_plain(client: _Client, title: str) -> str:
    data = client.json(
        "GET",
        WIKI_API,
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "exchars": 8000,
            "titles": title,
            "format": "json",
        },
    )
    pages = ((data or {}).get("query") or {}).get("pages") or {}
    for page in pages.values():
        return (page.get("extract") or "")[:8000]
    return ""


def _wiki_wikitext(client: _Client, title: str, api: str = WIKI_API) -> str:
    data = client.json(
        "GET",
        api,
        params={"action": "parse", "page": title, "prop": "wikitext", "format": "json"},
    )
    raw = ((data or {}).get("parse") or {}).get("wikitext") or {}
    if isinstance(raw, dict):
        return raw.get("*") or ""
    return str(raw or "")


def _wiki_characters(client: _Client, title: str) -> list[dict[str, str]]:
    if not title:
        return []
    names: list[dict[str, str]] = []
    pages = [title, f"List of {title} characters", f"{title} (light novel)"]
    for page in pages:
        text = _wiki_wikitext(client, page)
        if text:
            _merge_names(names, _names_from_markup(text))
    return names


def _fandom_characters(client: _Client, title: str) -> list[dict[str, str]]:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        return []
    api = f"https://{slug}.fandom.com/api.php"
    names: list[dict[str, str]] = []
    for page in (title, "Characters", "List of characters", f"{title}/Characters"):
        text = _wiki_wikitext(client, page, api=api)
        if text:
            _merge_names(names, _names_from_markup(text))
    listing = client.json(
        "GET",
        api,
        params={
            "action": "query",
            "list": "categorymembers",
            "cmtitle": "Category:Characters",
            "cmlimit": 40,
            "format": "json",
        },
    )
    for row in ((listing or {}).get("query") or {}).get("categorymembers") or []:
        page = row.get("title") or ""
        if not page or page.startswith("Category:"):
            continue
        text = _wiki_wikitext(client, page, api=api)
        _merge_names(names, _names_from_markup(text + "\n" + page))
        if page and not any("\u3040" <= ch <= "\u9fff" for ch in page):
            native_hits = _names_from_markup(text)
            for pair in native_hits:
                if pair.get("english") and pair.get("native"):
                    _merge_names(names, [pair])
    return names


def _names_from_markup(text: str) -> list[dict[str, str]]:
    names: list[dict[str, str]] = []
    for match in re.finditer(
        r"\{\{[Nn]ihongo\|([^|{}]+)\|([^|{}]+)",
        text or "",
    ):
        english = _clean_en_name(match.group(1))
        native = _clean_ja_name(match.group(2))
        if _is_person_name(native, english):
            names.append({"native": native, "english": english})
    for match in re.finditer(
        r"([A-Z][A-Za-z][\w'.-]*(?: [A-Z][A-Za-z][\w'.-]*){0,3})\s*[（(]([^)）]{1,32})[)）]",
        text or "",
    ):
        english, native = _clean_en_name(match.group(1)), _clean_ja_name(match.group(2))
        if _is_person_name(native, english):
            names.append({"native": native, "english": english})
    return names


def _clean_en_name(text: str) -> str:
    text = re.sub(r"\[\[|\]\]|'+", "", text or "")
    return text.strip(" \"'")


def _clean_ja_name(text: str) -> str:
    text = re.sub(r"\[\[|\]\]", "", text or "")
    text = re.split(r"[,，;；]", text, 1)[0]
    text = re.sub(r"'+[A-Za-z].*", "", text)
    return re.sub(r"'+", "", text).strip()


def _is_person_name(native: str, english: str) -> bool:
    if not native or not english:
        return False
    if len(native) > 24 or len(english) > 40:
        return False
    if not any("\u3040" <= ch <= "\u9fff" for ch in native):
        return False
    words = [w for w in re.split(r"\s+", english) if w]
    if not 1 <= len(words) <= 4:
        return False
    skip = {"japan", "japanese", "english", "light", "novel", "anime", "manga", "volume", "season", "honzuki"}
    if any(w.lower().strip('"') in skip for w in words):
        return False
    if english.lower().startswith(("at ", "the ", "list ")):
        return False
    return True


def _mangaupdates(client: _Client, queries: list[str]) -> dict:
    record = {}
    for query in queries:
        data = client.json(
            "POST",
            MU_SEARCH,
            json={"search": query, "perpage": 5, "stype": "title"},
        )
        for row in (data or {}).get("results") or []:
            rec = row.get("record") or {}
            title = rec.get("title") or ""
            if _related(query, title, rec.get("description") or ""):
                record = rec
                break
        if record:
            break
    if not record:
        return {}
    sid = record.get("series_id")
    detail = client.json("GET", MU_SERIES.format(sid=sid)) if sid else None
    rec = detail or record
    available = []
    kind = _mu_kind(rec.get("type") or record.get("type") or "")
    if kind:
        available.append(kind)
    publishers = []
    for pub in rec.get("publishers") or []:
        name = (pub.get("publisher_name") or pub.get("name") or "").strip()
        ptype = (pub.get("type") or "").lower()
        if name and ptype in {"english", "licensed", "en"}:
            publishers.append(name)
        elif name and _publishers_from_text(name):
            publishers.append(_publishers_from_text(name)[0])
    names = []
    for assoc in rec.get("associated") or []:
        title = (assoc.get("title") if isinstance(assoc, dict) else str(assoc)).strip()
        if title and any("\u3040" <= ch <= "\u9fff" for ch in title) and rec.get("title"):
            names.append({"native": title, "english": rec.get("title") or ""})
    authors = rec.get("authors") or []
    author = ""
    if authors:
        first = authors[0]
        author = first.get("name") if isinstance(first, dict) else str(first)
    return {
        "title": rec.get("title") or record.get("title") or "",
        "author": author,
        "available": available,
        "publishers": publishers,
        "names": names,
        "url": rec.get("url") or record.get("url") or "",
    }


def _jikan(client: _Client, queries: list[str]) -> dict:
    hits: list[dict] = []
    for query in queries[:3]:
        for url, kind in ((JIKAN_MANGA, "manga"), (JIKAN_ANIME, "anime")):
            data = client.json("GET", url, params={"q": query, "limit": 3})
            for item in (data or {}).get("data") or []:
                titles = " ".join(
                    t.get("title") or "" for t in (item.get("titles") or [])
                ) or (item.get("title") or "")
                if not _related(query, titles, item.get("synopsis") or ""):
                    continue
                hits.append({"kind": kind, "item": item})
        if hits:
            break
    if not hits:
        return {}
    available = []
    publishers = []
    links = []
    names = []
    title = ""
    author = ""
    manga_id = None
    for hit in hits:
        item = hit["item"]
        jtype = (item.get("type") or "").lower()
        if hit["kind"] == "anime":
            label = "Anime"
        elif "novel" in jtype:
            label = "Light novel"
        else:
            label = "Manga"
        if label not in available:
            available.append(label)
        title = title or item.get("title_english") or item.get("title") or ""
        for person in item.get("authors") or []:
            author = author or (person.get("name") or "")
        for house in item.get("serializations") or []:
            name = house.get("name") or ""
            if name and name not in publishers and _publishers_from_text(name):
                publishers.append(_publishers_from_text(name)[0])
        mal = (item.get("url") or "").strip()
        if mal:
            links.append({"label": f"MyAnimeList {label}", "url": mal})
        if hit["kind"] == "manga" and not manga_id:
            manga_id = item.get("mal_id")
    if manga_id:
        chars = client.json("GET", JIKAN_CHARS.format(mid=manga_id))
        for row in (chars or {}).get("data") or []:
            ch = row.get("character") or {}
            native = (ch.get("name_kanji") or "").strip()
            english = (ch.get("name") or "").strip()
            if native and english:
                names.append({"native": native, "english": english})
    return {
        "title": title,
        "author": author.replace(",", "").strip() if author and "," in author else author,
        "available": available,
        "publishers": publishers,
        "names": names[:40],
        "links": links,
    }


def _novelupdates(client: _Client, queries: list[str]) -> dict:
    for query in queries:
        response = client.get(NU_SEARCH, params={"s": query, "post_type": "seriessearch"})
        if response is None:
            return {}
        html = response.text
        match = re.search(
            r'<a[^>]+class="[^"]*search_title[^"]*"[^>]+href="(https://www\.novelupdates\.com/series/[^"]+)"[^>]*>([^<]+)',
            html,
            flags=re.I,
        )
        if not match:
            match = re.search(
                r'href="(https://www\.novelupdates\.com/series/[^"]+)"[^>]*>([^<]+)',
                html,
                flags=re.I,
            )
        if not match:
            continue
        url, title = match.group(1), re.sub(r"\s+", " ", match.group(2)).strip()
        if not _related(query, title, html[:4000]):
            continue
        page = client.get(url)
        body = page.text if page is not None else ""
        available = ["Light novel"]
        if re.search(r"associated names|manga", body, flags=re.I):
            if "Manga" not in available and re.search(r">\s*Manga\s*<", body, flags=re.I):
                available.append("Manga")
        return {
            "title": title,
            "url": url,
            "available": available,
            "publishers": _publishers_from_text(body or html),
        }
    return {}


def _fandom(client: _Client, query: str) -> dict:
    if not query:
        return {}
    data = client.json(
        "GET",
        FANDOM_SEARCH,
        params={"action": "opensearch", "search": query, "limit": 1, "format": "json"},
    )
    if not isinstance(data, list) or len(data) < 4 or not data[3]:
        return {}
    url = data[3][0]
    title = data[1][0] if data[1] else query
    if "fandom.com" not in url:
        return {}
    parsed = urlparse(url)
    api = f"{parsed.scheme}://{parsed.netloc}/api.php"
    extract_data = client.json(
        "GET",
        api,
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "exchars": 4000,
            "titles": title,
            "format": "json",
        },
    )
    extract = ""
    pages = ((extract_data or {}).get("query") or {}).get("pages") or {}
    for page in pages.values():
        extract = page.get("extract") or ""
    names = []
    for match in re.finditer(
        r"([A-Z][\w.'-]+(?: [A-Z][\w.'-]+)+)\s*[（(]([^)）]+)[)）]",
        extract,
    ):
        english, native = match.group(1), match.group(2)
        if any("\u3040" <= ch <= "\u9fff" for ch in native):
            names.append({"native": native, "english": english})
    return {"url": url, "extract": extract, "names": names[:20]}


def _mu_kind(raw: str) -> str:
    text = (raw or "").lower()
    if "novel" in text:
        return "Light novel"
    if "anime" in text:
        return "Anime"
    if text:
        return "Manga"
    return ""


def _related(query: str, title: str, extract: str) -> bool:
    q = (query or "").strip()
    if not q:
        return False
    head = re.split(r"[～〜~]", q, 1)[0].strip()
    hay = f"{title} {extract}"
    if q in hay or head in hay or q.lower() in hay.lower() or head.lower() in hay.lower():
        return True
    tokens = [t.lower() for t in re.split(r"[\s/~～〜\-:：・]+", q) if len(t) >= 4]
    low = hay.lower()
    hits = sum(1 for t in tokens if t in low)
    return hits >= 1 and (len(tokens) <= 2 or hits >= 2)


def _author_from_text(extract: str) -> str:
    match = re.search(r"written by ([A-Z][\w.'-]+(?: [A-Z][\w.'-]+)+)", extract or "")
    return match.group(1).rstrip(".,") if match else ""


def _native_from_text(extract: str) -> str:
    match = re.search(r"Japanese:\s*([^,;(]+)", extract or "")
    return match.group(1).strip() if match else ""


def _publishers_from_text(extract: str) -> list[str]:
    found = []
    for match in re.finditer(
        r"(J-Novel Club|Yen Press|Seven Seas|Viz Media|Kodansha USA|Kodansha|Square Enix|"
        r"Vertical|Sentai|Crunchyroll|BookWalker|TO Books|One Peace|Cross Infinite)",
        extract or "",
        flags=re.I,
    ):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def _merge_media(available: list[str], text: str) -> None:
    for label, pretty in (("light novel", "Light novel"), ("manga", "Manga"), ("anime", "Anime")):
        if label in (text or "").lower() and pretty not in available:
            available.append(pretty)


def _merge_pubs(publishers: list[str], text: str) -> None:
    for pub in _publishers_from_text(text):
        if pub not in publishers:
            publishers.append(pub)


def _merge_list(dest: list[str], extra: list[str]) -> None:
    for item in extra:
        if item and item not in dest:
            dest.append(item)


def _merge_names(dest: list[dict[str, str]], extra: list[dict[str, str]]) -> None:
    seen = {row.get("native") for row in dest}
    for pair in extra:
        key = pair.get("native")
        if key and key not in seen:
            seen.add(key)
            dest.append(pair)


def _add_link(links: list[dict[str, str]], label: str, url: str) -> None:
    if not label or not url:
        return
    if any(row.get("url") == url for row in links):
        return
    links.append({"label": label, "url": url})
