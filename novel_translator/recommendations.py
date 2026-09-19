from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import httpx
from bs4 import BeautifulSoup

from novel_translator.config import APP_DIR, load_config
from novel_translator.syosetu import USER_AGENT, novel_page_url
from novel_translator.wiki_lookup import lookup_official

CACHE_PATH = APP_DIR / "recommendations_cache.json"
CACHE_TTL_SEC = 12 * 60 * 60
LIVECHART_RANKINGS = (
    "https://www.livechart.me/rankings/anime"
    "?anime_format=tv&metric=popularity&page=1&release_status=not_yet_released"
)
SYOSETU_API = "https://api.syosetu.com/novelapi/api/"
JIKAN_ANIME = "https://api.jikan.moe/v4/anime"

_SEASON_TAIL = re.compile(
    r"\s*(?:"
    r"season\s*\d+|cour\s*\d+|"
    r"(?:\d+(?:st|nd|rd|th)\s*season)|"
    r"2nd\s*season|3rd\s*season|4th\s*season|"
    r"second\s*season|third\s*season|final\s*season|part\s*\d+|"
    r"\d+(?:st|nd|rd|th)|ii+|iii|iv|"
    r"シーズン\s*\d+|第\s*\d+\s*期|第\s*\d+\s*クール|クール\s*\d+|"
    r"第[一二三四五六七八九十\d]+\s*(?:幕|期)|"
    r"[二三四五]?期$"
    r")\s*$",
    flags=re.I,
)
_JP_CHARS = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def peek_cache(limit: int = 12) -> dict[str, Any]:
    cached = _load_cache()
    if not cached.get("items"):
        return {
            "ok": True,
            "source": "",
            "updated": "",
            "message": "Open Recommended and refresh to load upcoming anime.",
            "items": [],
        }
    items = (cached.get("items") or [])[:limit]
    fresh = _cache_fresh(cached)
    return {
        "ok": True,
        "source": "cache",
        "updated": cached.get("updated") or "",
        "message": (
            f"Cached recommendations ({len(items)} titles)."
            if fresh
            else f"Cached recommendations ({len(items)} titles) — refresh for newer anime."
        ),
        "items": items,
    }


def list_upcoming(
    limit: int = 12,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    log = progress or (lambda _msg: None)
    cached = _load_cache()
    if not force and cached and _cache_fresh(cached):
        items = (cached.get("items") or [])[:limit]
        return {
            "ok": True,
            "source": "cache",
            "updated": cached.get("updated") or "",
            "message": f"Cached recommendations ({len(items)} titles).",
            "items": items,
        }

    log("Loading upcoming anime from LiveChart…")
    try:
        raw = _fetch_livechart_upcoming(max(limit * 2, 16))
    except Exception as exc:
        if cached and cached.get("items"):
            items = (cached.get("items") or [])[:limit]
            return {
                "ok": True,
                "source": "cache",
                "updated": cached.get("updated") or "",
                "message": f"LiveChart unavailable ({exc}). Showing cached list.",
                "items": items,
            }
        return {
            "ok": False,
            "source": "",
            "updated": "",
            "message": f"Could not load LiveChart: {exc}",
            "items": [],
        }

    items: list[dict[str, Any]] = []
    prior_by_id = {
        str(row.get("id") or ""): row
        for row in (cached.get("items") or [])
        if isinstance(row, dict)
    }
    for idx, anime in enumerate(raw[: max(limit, 1)], start=1):
        title_en = anime.get("title_en") or ""
        log(f"Matching Syosetu ({idx}/{min(limit, len(raw))}): {title_en[:48]}…")
        card = _enrich_anime(anime, prior=prior_by_id.get(str(anime.get("id") or "")))
        items.append(card)
        if len(items) >= limit:
            break
        time.sleep(0.55)

    with_web = sum(1 for row in items if row.get("has_webnovel"))
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
    }
    _save_cache(payload)
    return {
        "ok": True,
        "source": "live",
        "updated": payload["updated"],
        "message": f"Loaded {len(items)} upcoming titles ({with_web} with Syosetu web novels).",
        "items": items,
    }


def recommend_for_title(title: str, ncode: str = "", books_root: str | Path | None = None) -> dict[str, Any]:
    title = (title or "").strip()
    official: dict[str, Any] = {}
    roots: list[Path] = []
    if books_root:
        roots.append(Path(books_root))
    try:
        cfg_out = Path(load_config().get("output_dir") or "")
        if cfg_out:
            roots.append(cfg_out / "books")
    except Exception:
        pass
    roots.append(Path.home() / "Documents" / "NovelTranslator" / "books")
    if ncode:
        for root in roots:
            candidate = root / ncode / "official.json"
            if candidate.exists():
                try:
                    official = json.loads(candidate.read_text(encoding="utf-8"))
                    break
                except Exception:
                    pass
    if not official and title:
        try:
            official = lookup_official(title, title, "")
        except Exception:
            official = {}

    upcoming = list_upcoming(limit=12, force=False)
    similar = []
    needle = _normalize(title)
    for item in upcoming.get("items") or []:
        blob = _normalize(
            " ".join(
                [
                    item.get("title_en") or "",
                    item.get("title_jp") or "",
                    item.get("official_title") or "",
                ]
            )
        )
        if not needle or needle[:8] in blob or any(tok in blob for tok in needle.split() if len(tok) > 4):
            if item.get("title_en") and _normalize(item.get("title_en") or "") != needle:
                similar.append(item)
        if len(similar) >= 8:
            break
    if len(similar) < 6:
        for item in upcoming.get("items") or []:
            if item in similar:
                continue
            similar.append(item)
            if len(similar) >= 8:
                break

    return {
        "title": title,
        "ncode": ncode,
        "official": {
            "found": bool(official.get("found")),
            "official_title": official.get("official_title") or "",
            "available": official.get("available") or [],
            "publishers": official.get("publishers") or [],
            "links": official.get("links") or [],
            "summary": (official.get("summary") or "")[:500],
        },
        "similar": similar,
        "message": upcoming.get("message") or "",
    }


def _enrich_anime(anime: dict[str, Any], prior: dict[str, Any] | None = None) -> dict[str, Any]:
    title_en = anime.get("title_en") or ""
    title_jp = anime.get("title_jp") or ""
    livechart_url = anime.get("livechart_url") or ""
    prior = prior or {}

    if livechart_url and (not title_jp or not _JP_CHARS.search(title_jp)):
        details = _livechart_details(livechart_url)
        title_jp = details.get("title_jp") or title_jp
        if details.get("title_romaji") and not title_en:
            title_en = details["title_romaji"]

    if not title_jp or not _JP_CHARS.search(title_jp):
        title_jp = _jikan_native_title(title_en) or title_jp or (prior.get("title_jp") or "")

    hit = _find_syosetu_webnovel(title_jp, title_en)
    ncode = (hit.get("ncode") or "").lower()
    syosetu_title = hit.get("title") or ""
    webnovel_url = novel_page_url(ncode) if ncode else ""

    official_title = prior.get("official_title") or ""
    available: list[str] = list(prior.get("available") or []) or ["Anime"]
    publishers: list[str] = list(prior.get("publishers") or [])
    if not prior.get("official_title") and not prior.get("publishers"):
        try:
            info = lookup_official(title_jp or title_en, title_en, "")
            official_title = info.get("official_title") or official_title
            for kind in info.get("available") or []:
                if kind not in available:
                    available.append(kind)
            publishers = list(info.get("publishers") or publishers)
        except Exception:
            pass
    if webnovel_url and "Web novel" not in available:
        available.append("Web novel")

    return {
        "id": anime.get("id") or "",
        "title_en": title_en,
        "title_jp": title_jp or syosetu_title or (prior.get("title_jp") or ""),
        "cover_url": anime.get("cover_url") or prior.get("cover_url") or "",
        "livechart_url": livechart_url,
        "premiere": anime.get("premiere") or prior.get("premiere") or "Upcoming",
        "webnovel_url": webnovel_url,
        "ncode": ncode,
        "has_webnovel": bool(ncode),
        "official_title": official_title or title_en,
        "available": available,
        "publishers": publishers,
    }


def _livechart_details(url: str) -> dict[str, str]:
    if not url:
        return {}
    last: dict[str, str] = {}
    for attempt in range(2):
        try:
            with httpx.Client(timeout=25, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
                response = client.get(url)
                if response.status_code >= 400:
                    time.sleep(0.4)
                    continue
                html = response.text
        except httpx.HTTPError:
            time.sleep(0.4)
            continue
        soup = BeautifulSoup(html, "lxml")
        romaji = ""
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            romaji = _search_query(og["content"])

        title_jp = ""
        text = soup.get_text("\n", strip=True)
        match = re.search(
            r"Original title\s*\n\s*([^\n]+)",
            text,
            flags=re.I,
        )
        if not match:
            match = re.search(
                r"Original title\s+([^\n]+?)(?:\s+Status|\s+Premiere|\s*$)",
                text,
                flags=re.I,
            )
        if match:
            candidate = match.group(1).strip()
            candidate = re.sub(r"^(?:Original title)\s*", "", candidate, flags=re.I)
            candidate = re.split(r"\s{2,}|\bStatus\b|\bPremiere\b", candidate, maxsplit=1)[0].strip()
            if _JP_CHARS.search(candidate):
                title_jp = _search_query(candidate)
        if not title_jp:
            # Prefer the compact native-title block; ignore related-anime noise elsewhere.
            for node in soup.select("div.text-sm"):
                candidate = node.get_text(" ", strip=True)
                candidate = re.sub(r"^(?:Original title)\s*", "", candidate, flags=re.I).strip()
                if not _JP_CHARS.search(candidate):
                    continue
                if len(candidate) > 90:
                    continue
                if re.search(r"\b(?:Status|Premiere|Format|Studio|Hashtags|Website)\b", candidate, flags=re.I):
                    continue
                if not candidate.lower().startswith("original") and "Original title" in (node.get_text(" ", strip=True) or ""):
                    # Node was "Original title …" and we already stripped the label.
                    pass
                title_jp = _search_query(candidate)
                if title_jp and _JP_CHARS.search(title_jp):
                    break
        # Do not scan the whole page for Japanese — related titles pollute matches.
        last = {"title_jp": title_jp, "title_romaji": romaji}
        if title_jp:
            return last
        time.sleep(0.35)
    return last


def _find_syosetu_webnovel(title_jp: str, title_en: str = "") -> dict[str, Any]:
    queries: list[str] = []
    # Syosetu is Japanese-first. Prefer the original title; English rarely matches.
    sources = [title_jp]
    if not title_jp or not _JP_CHARS.search(title_jp):
        sources.append(title_en)
    for raw in sources:
        cleaned = _search_query(raw)
        if not cleaned:
            continue
        # Drop short Latin-only queries (false positives like "Shangri").
        if not _JP_CHARS.search(cleaned) and len(re.findall(r"[a-z0-9]{3,}", cleaned.lower())) < 3:
            continue
        if cleaned not in queries:
            queries.append(cleaned)
        if cleaned and _JP_CHARS.search(cleaned) and len(cleaned) > 20:
            short = cleaned[:20].rstrip(" 　、。・")
            if short not in queries:
                queries.append(short)

    best: dict[str, Any] = {}
    best_score = 0
    for query in queries:
        for row in _syosetu_search_rows(query):
            score = _syosetu_score(query, row.get("title") or "")
            if score > best_score:
                best_score = score
                best = row
        if best_score >= 8:
            break
        time.sleep(0.2)

    # Require a strong title relationship — reject review/blog posts that only mention the name.
    if best_score < 6:
        return {}
    return {
        "ncode": (best.get("ncode") or "").lower(),
        "title": best.get("title") or "",
        "writer": best.get("writer") or "",
        "score": best_score,
    }


def _fetch_livechart_upcoming(limit: int) -> list[dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        response = client.get(LIVECHART_RANKINGS)
        if response.status_code == 403:
            raise RuntimeError("LiveChart returned 403")
        response.raise_for_status()
        html = response.text
    soup = BeautifulSoup(html, "lxml")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for img in soup.select("img[data-anime-item-target=poster], img.lc-aspect-poster"):
        title = (img.get("alt") or "").strip()
        src = img.get("src") or ""
        match = re.search(r"/anime/(\d+)/", src)
        anime_id = match.group(1) if match else ""
        href = f"https://www.livechart.me/anime/{anime_id}" if anime_id else ""
        parent = img.find_parent("div")
        for _ in range(6):
            if not parent:
                break
            link = parent.find("a", href=True)
            if link and "/anime/" in (link.get("href") or ""):
                href = link.get("href") or href
                title = title or link.get_text(" ", strip=True)
                break
            parent = parent.parent if hasattr(parent, "parent") else None
        if href.startswith("/"):
            href = "https://www.livechart.me" + href
        if not title or not href or href in seen:
            continue
        seen.add(href)
        if src and src.startswith("//"):
            src = "https:" + src
        rows.append(
            {
                "id": anime_id,
                "title_en": title,
                "title_jp": "",
                "cover_url": src,
                "livechart_url": href,
                "premiere": "Not yet released",
            }
        )
        if len(rows) >= limit:
            break
    if not rows:
        raise RuntimeError("No upcoming titles parsed from LiveChart")
    return rows


def _syosetu_search_rows(query: str) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if len(q) < 2:
        return []
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(
                SYOSETU_API,
                params={"out": "json", "word": q, "lim": 10, "order": "hyoka"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    return [row for row in payload[1:] if isinstance(row, dict)]


def _syosetu_score(query: str, title: str) -> int:
    q = _search_query(query)
    t = _search_query(title)
    needle = _normalize(q)
    hay = _normalize(t)
    if not needle or not hay:
        return 0
    if needle == hay:
        return 10
    # Official Syosetu titles are often "Name～long subtitle～".
    if t.startswith(q):
        rest = t[len(q) :].lstrip(" 　")
        if not rest:
            return 10
        if rest[0] in "～〜―－—−-:：・「『【(（":
            return 9
        # Review/blog posts: "Titleの…", "Titleは…", etc.
        if rest[0] in "のにはがをでともへ":
            return 1
        if len(rest) <= 36:
            return 8
        return 2
    if needle.startswith(hay) and len(needle) <= len(hay) + 12:
        return 8
    if needle in hay:
        if len(hay) > len(needle) * 2 + 10:
            return 1
        return 7
    score = 0
    for chunk in re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]{4,}", q):
        if _normalize(chunk) in hay:
            score += 3
    for tok in re.findall(r"[a-z0-9]{3,}", needle):
        if tok in hay:
            score += 1
    if score and len(hay) > len(needle) * 2 + 20:
        return min(score, 2)
    return score


def _jikan_native_title(english: str) -> str:
    q = _search_query(english)
    if len(q) < 3:
        return ""
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(JIKAN_ANIME, params={"q": q, "limit": 3})
            if response.status_code >= 400:
                return ""
            data = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return ""
    needle = _normalize(english)
    for item in data.get("data") or []:
        titles = item.get("titles") or []
        en = item.get("title_english") or item.get("title") or ""
        if _title_score(needle, _normalize(en)) < 2 and needle not in _normalize(en):
            continue
        for row in titles:
            if (row.get("type") or "").lower() == "japanese" and row.get("title"):
                return row["title"]
        native = item.get("title_japanese") or ""
        if native:
            return native
    return ""


def _search_query(text: str) -> str:
    cleaned = (text or "").strip()
    # Peel season / cour suffixes repeatedly (e.g. "第3期 第1クール").
    for _ in range(4):
        nxt = _SEASON_TAIL.sub("", cleaned).strip(" -–—·|/")
        if nxt == cleaned:
            break
        cleaned = nxt
    cleaned = re.sub(r"[\[\(\{].*?[\]\)\}]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—·|/")
    return cleaned[:80]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\u3040-\u30ff\u4e00-\u9fff]+", "", (text or "").lower())


def _title_score(needle: str, hay: str) -> int:
    if not needle or not hay:
        return 0
    if needle == hay or needle in hay or hay in needle:
        return 5
    tokens = [t for t in re.findall(r"[a-z0-9\u3040-\u30ff\u4e00-\u9fff]{3,}", needle)]
    return sum(1 for t in tokens if t in hay)


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(payload: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_fresh(cached: dict[str, Any]) -> bool:
    raw = cached.get("updated") or ""
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return age < CACHE_TTL_SEC and bool(cached.get("items"))
    except Exception:
        return False
