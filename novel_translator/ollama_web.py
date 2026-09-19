from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from novel_translator.providers import OLLAMA_BASE

OLLAMA_SEARCH = "https://ollama.com/api/web_search"
OLLAMA_FETCH = "https://ollama.com/api/web_fetch"
DDG = "https://html.duckduckgo.com/html/"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web for official English titles, publishers, and adaptations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a web page. Skip any site that refuses access.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]

PROMPT = """Look up whether this Japanese web novel has an official English book, manga, or anime.
Use web_search and web_fetch. Prefer Wikipedia, MangaUpdates, Novel Updates, publisher sites, and fansites.
Do not invent names or licenses. If a page is blocked, try another source.

Japanese title: {japanese}
English draft title: {english}
Author: {author}

When finished, output ONLY JSON:
{{
  "official_title": "",
  "author_english": "",
  "available": [],
  "publishers": [],
  "names": [{{"native": "", "english": ""}}],
  "links": [{{"label": "", "url": ""}}],
  "summary": ""
}}
available items must be one of: "Light novel", "Manga", "Anime".
names are official English character or creator spellings paired with Japanese.
"""


def lookup_with_ollama(
    japanese_title: str,
    english_title: str = "",
    author: str = "",
    model: str = "",
    api_key: str = "",
) -> dict[str, Any]:
    model = (model or "").strip()
    if not model:
        return {}
    key = (api_key or os.environ.get("OLLAMA_API_KEY") or "").strip()
    tools = _ToolBox(key)
    try:
        if not _ollama_up():
            return {}
        messages = [
            {
                "role": "user",
                "content": PROMPT.format(
                    japanese=japanese_title or "",
                    english=english_title or "",
                    author=author or "",
                ),
            }
        ]
        with httpx.Client(timeout=120) as client:
            for _ in range(5):
                data = _chat(client, model, messages)
                message = data.get("message") or {}
                calls = message.get("tool_calls") or []
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content") or "",
                        "tool_calls": calls,
                    }
                )
                if not calls:
                    return _parse_json(message.get("content") or "")
                for call in calls:
                    fn = (call.get("function") or {}) if isinstance(call, dict) else {}
                    name = fn.get("name") or ""
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    result = tools.run(name, args if isinstance(args, dict) else {})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": name,
                            "content": result[:8000],
                        }
                    )
    except httpx.HTTPError:
        return {}
    finally:
        tools.close()
    return {}


def _ollama_up() -> bool:
    try:
        response = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=2)
        return response.status_code < 400
    except httpx.HTTPError:
        return False


def _chat(client: httpx.Client, model: str, messages: list[dict]) -> dict:
    response = client.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "tools": TOOLS,
            "options": {"temperature": 0.1, "num_predict": 2048},
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def _parse_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    names = []
    for row in data.get("names") or []:
        if isinstance(row, dict) and row.get("native") and row.get("english"):
            names.append({"native": str(row["native"]), "english": str(row["english"])})
    links = []
    for row in data.get("links") or []:
        if isinstance(row, dict) and row.get("url"):
            links.append({"label": str(row.get("label") or "Source"), "url": str(row["url"])})
    allowed = {"Light novel", "Manga", "Anime"}
    available = [item for item in (data.get("available") or []) if item in allowed]
    publishers = [str(item) for item in (data.get("publishers") or []) if str(item).strip()]
    return {
        "official_title": str(data.get("official_title") or "").strip(),
        "author_english": str(data.get("author_english") or "").strip(),
        "available": available,
        "publishers": publishers,
        "names": names,
        "links": links,
        "summary": str(data.get("summary") or "").strip(),
    }


class _ToolBox:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.blocked: set[str] = set()
        self.http = httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": "NovelTranslator/1.0"},
        )

    def close(self) -> None:
        self.http.close()

    def run(self, name: str, args: dict[str, Any]) -> str:
        if name == "web_search":
            return self.search(str(args.get("query") or ""), int(args.get("max_results") or 5))
        if name == "web_fetch":
            return self.fetch(str(args.get("url") or ""))
        return f"Unknown tool: {name}"

    def search(self, query: str, max_results: int) -> str:
        query = query.strip()
        if not query:
            return "Empty query."
        max_results = max(1, min(max_results, 8))
        if self.api_key:
            cloud = self._ollama_search(query, max_results)
            if cloud:
                return cloud
        return self._ddg_search(query, max_results)

    def fetch(self, url: str) -> str:
        url = url.strip()
        if not url:
            return "Empty URL."
        if self.api_key:
            cloud = self._ollama_fetch(url)
            if cloud:
                return cloud
        return self._http_fetch(url)

    def _ollama_search(self, query: str, max_results: int) -> str:
        try:
            response = self.http.post(
                OLLAMA_SEARCH,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"query": query, "max_results": max_results},
            )
        except httpx.HTTPError:
            return ""
        if response.status_code == 403:
            return ""
        if response.status_code >= 400:
            return ""
        rows = (response.json() or {}).get("results") or []
        return json.dumps(rows[:max_results], ensure_ascii=False)

    def _ollama_fetch(self, url: str) -> str:
        try:
            response = self.http.post(
                OLLAMA_FETCH,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"url": url},
            )
        except httpx.HTTPError:
            return ""
        if response.status_code == 403:
            return ""
        if response.status_code >= 400:
            return ""
        data = response.json() or {}
        content = (data.get("content") or "")[:6000]
        return json.dumps(
            {"title": data.get("title") or "", "content": content, "links": (data.get("links") or [])[:12]},
            ensure_ascii=False,
        )

    def _ddg_search(self, query: str, max_results: int) -> str:
        response = self._get(DDG, method="POST", data={"q": query})
        if response is None:
            return "Search host blocked or unavailable."
        results = []
        for match in re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            response.text,
            flags=re.I | re.S,
        ):
            url, title = match.group(1), re.sub("<[^>]+>", "", match.group(2))
            title = re.sub(r"\s+", " ", title).strip()
            if url.startswith("http") and title:
                results.append({"title": title, "url": url})
            if len(results) >= max_results:
                break
        if not results:
            return "No search results."
        return json.dumps(results, ensure_ascii=False)

    def _http_fetch(self, url: str) -> str:
        response = self._get(url)
        if response is None:
            return "Page blocked or unavailable (including 403)."
        text = re.sub(r"<script[\s\S]*?</script>", " ", response.text, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()[:6000]
        return json.dumps({"title": "", "content": text, "url": str(response.url)}, ensure_ascii=False)

    def _get(self, url: str, method: str = "GET", **kwargs) -> httpx.Response | None:
        host = urlparse(url).netloc.lower()
        if host in self.blocked:
            return None
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError:
            return None
        if response.status_code == 403:
            self.blocked.add(host)
            return None
        if response.status_code >= 400:
            return None
        return response
