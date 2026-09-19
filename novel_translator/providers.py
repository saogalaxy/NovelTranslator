from __future__ import annotations

import httpx

OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_OPENAI = "http://127.0.0.1:11434/v1"
OPENAI_BASE = "https://api.openai.com/v1"


def list_ollama_models(timeout: float = 2.0) -> list[str]:
    try:
        response = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError:
        return []
    names = []
    for item in payload.get("models") or []:
        name = item.get("name") or item.get("model")
        if name:
            names.append(name)
    return names


def ollama_running() -> bool:
    return bool(list_ollama_models())
